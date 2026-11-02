"""Prepare or activate legacy source-job entrypoints with verified original backups."""
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

SOURCE_JOBS = Path(__file__).resolve().parent / 'source_jobs'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def launcher(name, editor_root):
    return ('"""Source job entrypoint; original preserved in the migration backup."""\n'
            'import os, runpy, sys\nfrom pathlib import Path\n'
            f'editor = Path(os.environ.get("EDITOR_ROOT") or {str(editor_root)!r})\n'
            'folder = editor / "infra/data/source_jobs"\n'
            'sys.path.insert(0, str(folder))\n'
            f'globals().update(runpy.run_path(str(folder / {name!r}), run_name=__name__))\n').encode('utf-8')


def private_values(index_root):
    values = {}
    assignments = {
        'download-ngii-original-probe.py': {'directory': 'NGII_PROBE_DIRECTORY'},
        'recover-ngii-package-manifest.py': {'prefix': 'NGII_ORDER_PREFIX', 'suffixes': 'NGII_ORDER_SUFFIXES_JSON'},
    }
    for filename, names in assignments.items():
        path = index_root / filename
        if not path.exists():
            continue
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in names:
                        try:
                            value = ast.literal_eval(node.value)
                        except (ValueError, TypeError):
                            continue
                        values[names[target.id]] = json.dumps(value) if target.id == 'suffixes' else value
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if isinstance(key, ast.Constant) and key.value == 'unityOrderNo' and isinstance(value, ast.Constant):
                        values['NGII_ORDER_NUMBER'] = value.value
    return values


def migrate(index_root, backup_root, *, apply=False, source_jobs=SOURCE_JOBS, private_config=None):
    index_root, backup_root = Path(index_root).resolve(), Path(backup_root).resolve()
    source_jobs = Path(source_jobs).resolve()
    editor = source_jobs.parents[2]
    manifest = json.loads((source_jobs / 'migration_manifest.json').read_text(encoding='utf-8-sig'))
    rows = []
    for item in manifest['source_files']:
        name = item['name']
        if Path(name).name != name or not name.endswith('.py'):
            raise ValueError('Invalid source manifest entry')
        original, target = index_root / name, source_jobs / name
        body = launcher(name, editor)
        current = digest(original)
        if current == hashlib.sha256(body).hexdigest():
            state = 'already_active'
        elif current == item['original_sha256']:
            state = 'ready'
        else:
            raise ValueError('Original source changed; review before activation: ' + name)
        rows.append(dict(name=name, state=state, original_sha256=item['original_sha256'],
                         target_sha256=digest(target), launcher_sha256=hashlib.sha256(body).hexdigest()))
    sensitive = private_values(index_root)
    private_config = Path(private_config or os.environ.get('NGII_SOURCE_JOB_CONFIG') or
                          Path(os.environ.get('DATA_ROOT') or 'C:/Data/25_ACE') / 'management/source-job-private.json').resolve()
    if source_jobs == private_config or source_jobs in private_config.parents or editor in private_config.parents:
        raise ValueError('Private configuration must stay outside the repository')
    existing = json.loads(private_config.read_text(encoding='utf-8')) if private_config.exists() else {}
    if private_config.exists() and any(key not in existing for key in sensitive):
        raise ValueError('Existing private configuration is incomplete; review outside the repository')
    if any(key in existing and existing[key] != value for key, value in sensitive.items()):
        raise ValueError('Private configuration differs; review outside the repository')
    result = dict(state='planned', index_root=str(index_root), source_jobs=str(source_jobs), files=rows,
                  private_config=str(private_config), private_fields=sorted(sensitive),
                  managed_sources={p.name: digest(p) for p in sorted(source_jobs.glob('*.py'))})
    if not apply:
        return result
    pending = [row for row in rows if row['state'] == 'ready']
    if not pending:
        result['state'] = 'already_active'
        return result
    if backup_root == index_root or backup_root == source_jobs or source_jobs in backup_root.parents:
        raise ValueError('Backups must be outside the source tree and separate from index root')
    backup_root.mkdir(parents=True, exist_ok=True)
    backup = backup_root / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup.mkdir()
    result['backup'] = str(backup)
    for row in pending:
        name = row['name']
        shutil.copy2(index_root / name, backup / name)
        if digest(backup / name) != row['original_sha256']:
            raise ValueError('Backup verification failed: ' + name)
    if sensitive and not private_config.exists():
        private_config.parent.mkdir(parents=True, exist_ok=True)
        with private_config.open('x', encoding='utf-8') as stream:
            stream.write(json.dumps(sensitive, indent=2) + '\n')
    if sensitive:
        result['private_config_sha256'] = digest(private_config)
    receipt = backup / 'receipt.json'
    result['state'] = 'backed_up'
    receipt.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    try:
        for row in pending:
            original = index_root / row['name']
            if digest(original) != row['original_sha256']:
                raise ValueError('Source changed during activation: ' + row['name'])
            with tempfile.NamedTemporaryFile(dir=index_root, prefix='.source-job-', suffix='.tmp', delete=False) as temporary:
                temporary.write(launcher(row['name'], editor))
                temporary_path = Path(temporary.name)
            temporary_path.replace(original)
            if digest(original) != row['launcher_sha256']:
                raise ValueError('Entrypoint verification failed: ' + row['name'])
            row['state'] = 'activated'
    except Exception:
        result['state'] = 'partial_activation'
        receipt.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
        raise
    result['state'] = 'activated'
    receipt.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index-root', type=Path, default=Path(os.environ.get('ACE_SOURCE_DATA_ROOT') or 'D:/Data/25_ACE/data') / 'index')
    parser.add_argument('--backup-root', type=Path, default=Path(os.environ.get('DATA_ROOT') or 'C:/Data/25_ACE') / 'management/source-job-backups')
    parser.add_argument('--apply', action='store_true', help='Back up originals, then replace entrypoints; never executes jobs')
    args = parser.parse_args()
    print(json.dumps(migrate(args.index_root, args.backup_root, apply=args.apply), indent=2))


if __name__ == '__main__':
    main()
