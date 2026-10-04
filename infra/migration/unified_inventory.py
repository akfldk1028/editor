"""Static migration evidence; mounted routes are not proof of working services."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import subprocess


def path_calls(source):
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'path' and len(node.args) >= 2:
            if not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[0].value, str):
                raise ValueError('Dynamic route requires manual inventory')
            yield node


def django_routes(root):
    root = Path(root)
    mounts = {}
    rows = []
    for call in path_calls((root / 'backend/urls.py').read_text(encoding='utf-8-sig')):
        view = call.args[1]
        if isinstance(view, ast.Call) and isinstance(view.func, ast.Name) and view.func.id == 'include':
            mounts[ast.literal_eval(view.args[0])] = call.args[0].value
        else:
            route = call.args[0].value
            rows.append({'id': 'arr:' + route, 'route': route, 'mounted': True,
                         'entrypoint': 'backend/urls.py', 'line': call.lineno,
                         'handler': ast.unparse(view)})
    for file in sorted(root.glob('*/urls.py')):
        if file.parent.name == 'backend':
            continue
        module = file.parent.name + '.urls'
        for call in path_calls(file.read_text(encoding='utf-8-sig')):
            route = mounts.get(module, file.parent.name + '/') + call.args[0].value
            rows.append({'id': 'arr:' + route, 'route': route, 'mounted': module in mounts,
                         'entrypoint': file.relative_to(root).as_posix(), 'line': call.lineno,
                         'handler': ast.unparse(call.args[1])})
    return rows


def fastapi_routes(web_root):
    web_root = Path(web_root)
    app = ast.parse((web_root / 'app.py').read_text(encoding='utf-8-sig'))
    imports = {}
    sources = [(web_root / 'app.py', '/api', 'api')]
    for node in app.body:
        if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
            for alias in node.names:
                imports[alias.asname or alias.name] = web_root / node.module.replace('.', '/') / (alias.name + '.py')
    for node in ast.walk(app):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or node.func.attr != 'include_router':
            continue
        if not isinstance(node.func.value, ast.Name) or node.func.value.id != 'api':
            continue
        reference = node.args[0]
        if not isinstance(reference, ast.Attribute) or not isinstance(reference.value, ast.Name):
            raise ValueError('Dynamic router requires manual inventory')
        file = imports[reference.value.id]
        prefix = next((ast.literal_eval(keyword.value) for keyword in node.keywords if keyword.arg == 'prefix'), '')
        sources.append((file, '/api' + prefix, reference.attr))
    rows = []
    for file, prefix, router in sources:
        tree = ast.parse(file.read_text(encoding='utf-8-sig'))
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                    continue
                method = decorator.func.attr.upper()
                if not isinstance(decorator.func.value, ast.Name) or decorator.func.value.id != router or method not in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS', 'WEBSOCKET'):
                    continue
                route = prefix + ast.literal_eval(decorator.args[0])
                rows.append({'id': f'ag:{method} {route}', 'route': route, 'method': method, 'mounted': True,
                             'entrypoint': file.relative_to(web_root).as_posix(), 'line': node.lineno, 'handler': node.name})
    return rows


def validate_coverage(operations, rows):
    indexed = {}
    for row in rows:
        if row['id'] in indexed:
            raise ValueError('duplicate operation: ' + row['id'])
        indexed[row['id']] = row
    for operation in operations:
        if not operation['mounted']:
            continue
        row = indexed.get(operation['id'])
        if not row:
            raise ValueError('missing operation: ' + operation['id'])
        if row.get('disposition') not in ('migrate', 'adapt', 'exclude', 'defer'):
            raise ValueError('missing disposition: ' + operation['id'])
        if row['disposition'] in ('exclude', 'defer'):
            if not row.get('reason'):
                raise ValueError('missing exclusion reason: ' + operation['id'])
        elif not row.get('target'):
            raise ValueError('missing target: ' + operation['id'])


def source_record(root, file, target):
    commit = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    return {'source': str(file), 'commit': commit, 'sha256': hashlib.sha256(file.read_bytes()).hexdigest(),
            'target': target, 'classification': 'source', 'basis': 'working-tree bytes; commit does not imply clean'}


def validate_sources(rows):
    for row in rows:
        file = Path(row['source'])
        if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest() != row['sha256']:
            raise ValueError('source changed since inventory: ' + row['source'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--arr', type=Path, required=True)
    parser.add_argument('--matrix', type=Path, required=True)
    parser.add_argument('--source-map', type=Path, required=True)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--ag-web', type=Path)
    args = parser.parse_args()
    operations = django_routes(args.arr / 'backend')
    if args.check:
        matrix = json.loads(args.matrix.read_text(encoding='utf-8'))
        if args.ag_web:
            operations += fastapi_routes(args.ag_web)
        validate_coverage(operations, matrix['features'])
        validate_sources(json.loads(args.source_map.read_text(encoding='utf-8'))['files'])
        print(json.dumps({'mounted_operations': sum(row['mounted'] for row in operations), 'coverage': 'mapped-not-implemented'}))
        return
    if args.matrix.exists() or args.source_map.exists():
        raise SystemExit('Refusing to overwrite curated migration evidence; use --check')
    rows = []
    for operation in operations:
        module = operation['entrypoint'].split('/')[0]
        rows.append({**operation, 'source_root': str(args.arr), 'entrypoint': 'backend/' + operation['entrypoint'],
                     'ui_actions': [], 'api_operations': [operation['route']], 'data_owner': 'ARR domain',
                     'target': 'backend/app/api/routes_' + module + '.py' if operation['mounted'] else None,
                     'disposition': 'migrate' if operation['mounted'] else 'defer',
                     'reason': 'Product API entry; domain/storage decomposition requires per-feature review' if operation['mounted'] else 'Not mounted by current root URL configuration',
                     'status': 'inventoried-not-migrated', 'evidence': ['Static URL declaration; HTTP method and UI action review pending']})
    validate_coverage(operations, rows)
    args.matrix.parent.mkdir(parents=True, exist_ok=True)
    args.matrix.write_text(json.dumps({'schema': 'editor-unified-functions/v1', 'scope': 'ARR Django path declarations only',
        'complete_inventory': False, 'pending': ['ARR UI actions', 'AG lightweight UI actions', 'AG backend operations',
        'CLI and registered agents', 'Shared agent transitive dependencies', 'Assets and preservation'], 'features': rows}, indent=2) + '\n', encoding='utf-8')
    files = sorted({args.arr / row['entrypoint'] for row in rows} | {args.arr / 'backend/backend/urls.py'})
    args.source_map.write_text(json.dumps({'schema': 'editor-unified-source-map/v1', 'complete_import_closure': False,
        'files': [source_record(args.arr, file, 'reference-only: per-feature source mapping pending') for file in files]}, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'declared_routes': len(rows), 'mounted_routes': sum(row['mounted'] for row in rows)}))


if __name__ == '__main__':
    main()
