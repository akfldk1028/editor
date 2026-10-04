"""Inventory Python imports using AST only; never import the inspected application."""
import argparse
import ast
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sys


EXCLUDED = {'.git', '.venv', 'venv', 'node_modules', '__pycache__'}


def inventory(source_root, entries, apps, tool_roots=(), include_commands=False,
              include_lazy_exports=False):
    root = Path(source_root).resolve()
    modules = {}
    collisions = []
    for search_root in [root, *map(Path, tool_roots)]:
        for path in sorted(search_root.rglob('*.py')):
            relative = path.relative_to(search_root)
            if EXCLUDED.intersection(relative.parts):
                continue
            name = '.'.join(relative.with_suffix('').parts)
            if name.endswith('.__init__'):
                name = name[:-9]
            if name in modules and modules[name] != path:
                collisions.append({'module': name, 'kept': str(modules[name]),
                                   'alternate': str(path)})
                continue
            modules[name] = path
    parsed = {}
    errors = []

    def parse(name):
        if name not in parsed:
            try:
                parsed[name] = ast.parse(modules[name].read_text(encoding='utf-8-sig'))
            except (SyntaxError, UnicodeError) as exc:
                errors.append({'file': str(modules[name]), 'error': str(exc)})
                parsed[name] = ast.Module(body=[], type_ignores=[])
        return parsed[name]

    aliases = {}

    def exports(name):
        if name not in aliases:
            aliases[name] = {}
            for node in parse(name).body:
                if not isinstance(node, ast.Assign):
                    continue
                identifiers = [t.id for t in node.targets if isinstance(t, ast.Name)]
                if not {'_EXPORTS', '_EXPORT_MODULES'}.intersection(identifiers):
                    continue
                try:
                    mapping = ast.literal_eval(node.value)
                except (ValueError, TypeError):
                    continue
                if not isinstance(mapping, dict):
                    continue
                for symbol, target in mapping.items():
                    if not isinstance(target, str):
                        continue
                    if '_EXPORTS' in identifiers and name == 'law':
                        target = 'law.core.' + target
                    elif target.startswith('.'):
                        target = name + target
                    aliases[name][symbol] = (target, node.lineno)
        return aliases[name]

    seed_reasons = defaultdict(list)
    for entry in entries:
        seed_reasons[entry].append('explicit-entry')
    for app in apps:
        seed_reasons[app].append('explicit-app')
        for suffix in ['', '.apps', '.models', '.admin']:
            if app + suffix in modules:
                seed_reasons[app + suffix].append('django-app-registry')
        for name in modules:
            if name.startswith(app + '.migrations.'):
                seed_reasons[name].append('django-migration')
            if include_commands and name.startswith(app + '.management.commands.'):
                seed_reasons[name].append('django-management-command')
    if include_lazy_exports:
        for name in ['law', 'design.maas']:
            if name in modules:
                for target, _ in exports(name).values():
                    seed_reasons[target].append('conservative-lazy-export')
    seen = set()
    queue = list(seed_reasons)
    edges = []
    dynamic = []
    nonlocal_refs = defaultdict(set)

    while queue:
        name = queue.pop()
        if name in seen or name not in modules:
            continue
        seen.add(name)
        path = modules[name]
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError:
            relative = path.as_posix()
        tree = parse(name)

        def add(target, line, kind):
            if target not in modules:
                return False
            edges.append({'file': relative, 'line': line, 'module': target, 'kind': kind})
            queue.append(target)
            return True

        for length in range(1, len(name.split('.'))):
            add('.'.join(name.split('.')[:length]), 1, 'package-init')
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for item in node.names:
                    if not add(item.name, node.lineno, 'import'):
                        nonlocal_refs[item.name].add((relative, node.lineno))
            elif isinstance(node, ast.ImportFrom):
                package = name if path.name == '__init__.py' else name.rpartition('.')[0]
                parts = package.split('.')
                base = '.'.join(parts[:len(parts) - node.level + 1]) if node.level else ''
                target = '.'.join(x for x in [base, node.module] if x)
                found = add(target, node.lineno, 'from')
                for item in node.names:
                    found = add(target + '.' + item.name, node.lineno, 'from-member') or found
                    if target in modules and item.name in exports(target):
                        alias, _ = exports(target)[item.name]
                        found = add(alias, node.lineno, 'lazy-export') or found
                        if alias not in modules:
                            nonlocal_refs[alias].add((relative, node.lineno))
                if not found:
                    nonlocal_refs[target].add((relative, node.lineno))
            elif isinstance(node, ast.Call):
                call = ast.unparse(node.func)
                if call.endswith(('import_module', '__import__', 'spec_from_file_location')) or call in ['sys.path.insert', 'sys.path.append']:
                    event = {'file': relative, 'line': node.lineno,
                             'expression': ast.unparse(node), 'resolution': 'computed-or-path'}
                    dynamic.append(event)
                    if call.endswith(('import_module', '__import__')) and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                        target = node.args[0].value
                        if call.endswith('__import__'):
                            level_arg = node.args[4] if len(node.args) > 4 else next(
                                (kw.value for kw in node.keywords if kw.arg == 'level'), None)
                            if level_arg is not None and not (isinstance(level_arg, ast.Constant) and level_arg.value == 0):
                                event['resolution'] = 'unresolved-builtin-relative-level'
                                continue
                        if target.startswith('.'):
                            package_arg = node.args[1] if len(node.args) > 1 else next(
                                (kw.value for kw in node.keywords if kw.arg == 'package'), None)
                            if not isinstance(package_arg, ast.Constant) or not isinstance(package_arg.value, str):
                                event['resolution'] = 'computed-package' if package_arg is not None else 'missing-package'
                                continue
                            depth = len(target) - len(target.lstrip('.'))
                            package_parts = package_arg.value.split('.')
                            if depth > len(package_parts):
                                event['resolution'] = 'relative-import-beyond-package'
                                continue
                            target = '.'.join(package_parts[:len(package_parts) - depth + 1] + [target.lstrip('.')]).rstrip('.')
                        event['resolved_module'] = target
                        event['resolution'] = 'literal-local' if target in modules else 'literal-nonlocal'
                        if not add(target, node.lineno, 'literal-dynamic'):
                            nonlocal_refs[target].add((relative, node.lineno))
                        if call.endswith('__import__'):
                            fromlist_arg = node.args[3] if len(node.args) > 3 else next(
                                (kw.value for kw in node.keywords if kw.arg == 'fromlist'), None)
                            if fromlist_arg is not None:
                                try:
                                    members = ast.literal_eval(fromlist_arg)
                                except (ValueError, TypeError):
                                    event['resolution'] = 'computed-fromlist'
                                    continue
                                if members is None:
                                    members = []
                                if not isinstance(members, (list, tuple)) or not all(isinstance(member, str) for member in members):
                                    event['resolution'] = 'unsupported-fromlist'
                                    continue
                                event['fromlist'] = list(members)
                                for member in members:
                                    if member == '*':
                                        event['resolution'] = 'unresolved-wildcard-fromlist'
                                    else:
                                        add(target + '.' + member, node.lineno, 'literal-dynamic-fromlist')
    local_names = {name.split('.')[0] for name in modules}
    groups = {name: [] for name in ['stdlib', 'third_party_candidate', 'unresolved_local']}
    for name, evidence in sorted(nonlocal_refs.items()):
        head = name.split('.')[0]
        category = ('unresolved_local' if head in local_names else
                    'stdlib' if head in sys.stdlib_module_names else 'third_party_candidate')
        groups[category].append({'module': name, 'evidence': [
            {'file': file, 'line': line} for file, line in sorted(evidence)]})
    inbound = defaultdict(list)
    unique_edges = [dict(zip(['file', 'line', 'module', 'kind'], values)) for values in sorted({
        (e['file'], e['line'], e['module'], e['kind']) for e in edges})]
    for edge in unique_edges:
        inbound[edge['module']].append({k: v for k, v in edge.items() if k != 'module'})
    return {
        'schema': 'arr-static-import-evidence/v1', 'source_root': root.as_posix(),
        'method': 'AST only; conservative function/optional imports; no application imports',
        'python_stdlib_classification_version': sys.version.split()[0],
        'counts': {'module_identities': len(seen),
                   'unique_physical_files': len({modules[name].resolve() for name in seen})},
        'source_files': [{'module': name, 'source': modules[name].as_posix(),
                          'sha256': hashlib.sha256(modules[name].read_bytes()).hexdigest(),
                          'seed_reasons': seed_reasons.get(name, []),
                          'evidence': inbound[name]} for name in sorted(seen)],
        'import_edges': unique_edges, 'nonlocal_imports': groups,
        'dynamic_import_and_path_evidence': dynamic,
        'missing_seeds': sorted(set(seed_reasons) - set(modules)),
        'module_collisions': collisions, 'parse_errors': errors,
        'limitations': [
            'Existing from-import packages may expose attributes; absent member names are not assumed missing modules.',
            'Only ARR _EXPORTS/_EXPORT_MODULES constant alias maps are recognized; other computed registries remain dynamic.',
            'Tool root name collisions retain the first root and require import-precedence review.',
            'Third-party candidates may contain externally supplied local modules; no installation check is performed.',
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--entry', action='append', default=[])
    parser.add_argument('--app', action='append', default=[])
    parser.add_argument('--tool-root', type=Path, action='append', default=[])
    parser.add_argument('--include-commands', action='store_true')
    parser.add_argument('--include-lazy-exports', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--overwrite', action='store_true')
    args = parser.parse_args()
    if not args.source_root.is_dir() or any(not p.is_dir() for p in args.tool_root):
        parser.error('Source and tool roots must be existing directories')
    if not args.entry and not args.app:
        parser.error('At least one --entry or --app is required')
    if args.output.exists() and not args.overwrite:
        parser.error('Output exists; pass --overwrite to replace it')
    result = inventory(args.source_root, args.entry, args.app, args.tool_root,
                       args.include_commands, args.include_lazy_exports)
    with args.output.open('w' if args.overwrite else 'x', encoding='utf-8') as handle:
        json.dump(result, handle, ensure_ascii=True, indent=2)
        handle.write('\n')
    print(json.dumps({'output': str(args.output), 'files': len(result['source_files']),
                      'parse_errors': len(result['parse_errors'])}))


if __name__ == '__main__':
    main()
