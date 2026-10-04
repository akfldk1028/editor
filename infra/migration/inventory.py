"""Read-only filesystem inventory; a manifest is not itself a backup.

Stop writers before a preservation scan: per-file race detection is not an atomic
filesystem snapshot. Link/reparse targets are recorded, never inventoried.
"""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys

SCHEMA = 'editor-migration-inventory/v1'
_snapshot_module = None


def link_metadata(path, info):
    global _snapshot_module
    if _snapshot_module is None:
        spec = importlib.util.spec_from_file_location('migration_snapshot_links', Path(__file__).with_name('snapshot.py'))
        _snapshot_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_snapshot_module)
    return _snapshot_module._link_metadata(path, info)


def valid_link(entry):
    raw = entry.get('reparse_data_base64')
    if raw is not None:
        try:
            data = base64.b64decode(raw, validate=True)
        except (ValueError, TypeError):
            return False
        if not data or hashlib.sha256(data).hexdigest() != entry.get('reparse_data_sha256'):
            return False
    return isinstance(entry.get('target'), str) or raw is not None


def linked(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def fingerprint(info):
    # Windows directory allocation size can vary by stat path without a tree change.
    size = 0 if os.name == 'nt' and stat.S_ISDIR(info.st_mode) and not linked(info) else info.st_size
    return (info.st_dev, info.st_ino, size, info.st_mtime_ns, info.st_ctime_ns)


def hash_file(path, before):
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        # Windows stat/fstat ctime can represent different native timestamps.
        if fingerprint(opened)[:4] != fingerprint(before)[:4]:
            raise ValueError('file_changed_during_hash')
        digest = hashlib.sha256()
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
        if fingerprint(os.fstat(stream.fileno())) != fingerprint(opened):
            raise ValueError('file_changed_during_hash')
        return digest.hexdigest()


def case_collisions(paths):
    seen, collisions = {}, []
    for path in paths:
        key = path.casefold()
        if key in seen and seen[key] != path:
            collisions.append([seen[key], path])
        seen[key] = path
    return collisions


def git_inventory(root):
    env = {**os.environ, 'GIT_OPTIONAL_LOCKS': '0', 'GIT_TERMINAL_PROMPT': '0', 'GIT_NO_LAZY_FETCH': '1'}
    def run(*args, optional=False, stdin=None):
        result = subprocess.run(['git', '-c', 'core.fsmonitor=false', '-C', str(root), *args],
                                capture_output=True, env=env,
                                input=stdin.encode('utf-8', errors='surrogateescape') if stdin is not None else None)
        if result.returncode:
            if optional and result.returncode == 1:
                return None
            raise ValueError('git_command_failed:' + args[0])
        return result.stdout.decode('utf-8', errors='surrogateescape')
    index = []
    for record in run('ls-files', '--stage', '-z').split('\0'):
        if record:
            metadata, path = record.split('\t', 1)
            mode, blob, stage = metadata.split()
            index.append({'path': path, 'mode': mode, 'blob': blob, 'stage': int(stage)})
    source_subpath = run('rev-parse', '--show-prefix').strip()
    filter_keys = run('config', '--name-only', '--get-regexp', r'^filter\..*\.(clean|process)$', optional=True)
    filter_keys = sorted(set(filter_keys.splitlines())) if filter_keys else []
    active_filter_keys = []
    if filter_keys and index:
        paths = sorted({entry['path'] for entry in index})
        attributes = run('check-attr', '-z', '--stdin', 'filter', stdin='\0'.join(paths) + '\0').split('\0')
        if attributes[-1] != '' or len(attributes[:-1]) != len(paths) * 3:
            raise ValueError('git_filter_attributes_unknown')
        active_names = set()
        for offset in range(0, len(attributes) - 1, 3):
            name, attribute, value = attributes[offset:offset + 3]
            if name != paths[offset // 3] or attribute != 'filter':
                raise ValueError('git_filter_attributes_unknown')
            if value not in ('unspecified', 'unset'):
                active_names.add(value)
        active_filter_keys = [key for key in filter_keys if key[len('filter.'):].rsplit('.', 1)[0] in active_names]
    # Even read-only status can run clean/process filters and mutate LFS storage.
    status_rows = None if active_filter_keys else []
    if not active_filter_keys:
        records = run('status', '--porcelain=v1', '-z', '--untracked-files=all', '--no-renames',
                      '--ignore-submodules=all', '--', '.').split('\0')
        for record in records:
            if record:
                name = record[3:]
                if source_subpath and not name.startswith(source_subpath):
                    raise ValueError('git_status_outside_source')
                status_rows.append({'status': record[:2], 'path': name[len(source_subpath):]})
    commit = run('rev-parse', '--verify', '--quiet', 'HEAD', optional=True)
    branch = run('symbolic-ref', '--quiet', '--short', 'HEAD', optional=True)
    return {'commit': commit.strip() if commit else None,
            'branch': branch.strip() if branch else None, 'index': index, 'status': status_rows,
            'status_inspected': not active_filter_keys,
            'status_skip_reason': 'configured_external_filters' if active_filter_keys else None,
            'status_submodules': 'excluded; nested repositories inventoried separately within source',
            'external_filter_keys': filter_keys,
            'active_filter_keys': active_filter_keys,
            'git_root': run('rev-parse', '--show-toplevel').strip(),
            'source_subpath': source_subpath,
            'untracked': [p for p in run('ls-files', '--others', '--exclude-standard', '-z').split('\0') if p],
            'ignored': [p for p in run('ls-files', '--others', '--ignored', '--exclude-standard', '-z').split('\0') if p]}


def safe_root(source):
    source = Path(os.path.abspath(source))
    for path in (source, *source.parents):
        if linked(path.lstat()):
            raise ValueError('source_root_or_ancestor_is_link')
    if not source.is_dir():
        raise ValueError('source_not_directory')
    return source


def scan(source, metadata_only=False):
    entries, errors, repositories = [], [], []
    result = {'schema_version': SCHEMA, 'source': str(Path(source).absolute()),
              'created_at': datetime.now(timezone.utc).isoformat(),
              'mode': 'metadata_only' if metadata_only else 'sha256',
              'complete': False, 'filesystem_complete': False, 'git_state_complete': False,
              'entries': entries, 'repositories': repositories, 'errors': errors,
              'scope': 'link_targets_excluded; stop writers for a consistent preservation scan'}
    def error(path, code, scope='filesystem'):
        errors.append({'path': str(path), 'code': code, 'scope': scope})
    try:
        root = safe_root(source)
    except (OSError, ValueError) as exc:
        error('.', str(exc) if isinstance(exc, ValueError) else type(exc).__name__)
        return result
    result['resolved_root'] = str(root.resolve())

    def repository(directory, marker):
        relative = directory.relative_to(root).as_posix()
        try:
            if linked(marker.lstat()):
                raise ValueError('git_marker_is_link')
            if not marker.is_dir():
                raise ValueError('external_git_pointer_not_inspected')
            repo = {'path': relative, **git_inventory(directory)}
            repositories.append(repo)
            if not repo['status_inspected']:
                error(relative, 'git_status_not_inspected_external_filters', 'git')
        except (OSError, ValueError) as exc:
            error(relative, str(exc) if isinstance(exc, ValueError) else type(exc).__name__, 'git')

    # Only query enclosing repository metadata; all file lists stay source-scoped.
    if not (root / '.git').exists() and not (root / '.git').is_symlink():
        for ancestor in root.parents:
            marker = ancestor / '.git'
            try:
                marker.lstat()
            except FileNotFoundError:
                continue
            except OSError as exc:
                error('.', type(exc).__name__, 'git')
                break
            repository(root, marker)
            break

    def visit(directory):
        relative = directory.relative_to(root).as_posix()
        try:
            before_directory = directory.lstat()
            if linked(before_directory):
                raise ValueError('directory_changed_to_link')
            children = sorted(directory.iterdir(), key=lambda p: p.name)
        except (OSError, ValueError) as exc:
            error(relative, str(exc) if isinstance(exc, ValueError) else type(exc).__name__)
            return
        if any(p.name == '.git' for p in children):
            repository(directory, directory / '.git')
        for path in children:
            name = path.relative_to(root).as_posix()
            try:
                before = path.lstat()
                item = {'path': name, 'mtime_ns': before.st_mtime_ns}
                if linked(before):
                    item.update(kind='link', **link_metadata(path, before))
                    if fingerprint(path.lstat()) != fingerprint(before):
                        raise ValueError('link_changed_during_scan')
                elif stat.S_ISDIR(before.st_mode):
                    item['kind'] = 'directory'
                    entries.append(item)
                    visit(path)
                    continue
                elif stat.S_ISREG(before.st_mode):
                    item.update(kind='file', size=before.st_size)
                    if not metadata_only:
                        item['sha256'] = hash_file(path, before)
                    if fingerprint(path.lstat()) != fingerprint(before):
                        raise ValueError('file_changed_during_hash')
                else:
                    raise ValueError('unsupported_file_type')
                entries.append(item)
            except (OSError, ValueError) as exc:
                error(name, str(exc) if isinstance(exc, ValueError) else type(exc).__name__)
        try:
            if fingerprint(directory.lstat()) != fingerprint(before_directory):
                error(relative, 'directory_changed_during_scan')
        except OSError as exc:
            error(relative, type(exc).__name__)
    visit(root)
    for collision in case_collisions([entry['path'] for entry in entries]):
        error(collision[0], 'case_collision:' + collision[1])
    result['filesystem_complete'] = not any(error['scope'] == 'filesystem' for error in errors)
    result['git_state_complete'] = not any(error['scope'] == 'git' for error in errors)
    result['complete'] = result['filesystem_complete'] and result['git_state_complete']
    return result


def verify(manifest, root):
    result = {'verified': False, 'missing': [], 'changed': [], 'extra': [], 'errors': []}
    if (not isinstance(manifest, dict) or manifest.get('schema_version') != SCHEMA
            or manifest.get('complete') is not True or manifest.get('mode') != 'sha256'
            or manifest.get('errors') != [] or not isinstance(manifest.get('entries'), list)):
        result['errors'].append({'code': 'incomplete_or_non_hash_manifest'})
        return result
    expected = {}
    for entry in manifest['entries']:
        if not isinstance(entry, dict):
            result['errors'].append({'code': 'invalid_entry'})
            return result
        path = entry.get('path', '')
        if (not isinstance(path, str) or not path or '\\' in path or ':' in path
                or PurePosixPath(path).is_absolute() or '..' in PurePosixPath(path).parts
                or str(PurePosixPath(path)) != path or path == '.' or path in expected
                or entry.get('kind') not in ('file', 'directory', 'link')
                or (entry['kind'] == 'file' and (not isinstance(entry.get('size'), int)
                    or not isinstance(entry.get('sha256'), str) or len(entry['sha256']) != 64))
                or (entry['kind'] == 'link' and not valid_link(entry))):
            result['errors'].append({'code': 'invalid_entry'})
            return result
        expected[path] = entry
    if case_collisions(expected):
        result['errors'].append({'code': 'case_collision'})
        return result
    actual = scan(root)
    result['errors'].extend(actual['errors'])
    observed = {entry['path']: entry for entry in actual['entries']}
    result['missing'] = sorted(expected.keys() - observed.keys())
    result['extra'] = sorted(observed.keys() - expected.keys())
    for name in expected.keys() & observed.keys():
        fields = ('kind', 'size', 'sha256', 'target', 'reparse_tag',
                  'reparse_data_base64', 'reparse_data_sha256')
        if any(expected[name].get(key) != observed[name].get(key) for key in fields):
            result['changed'].append(name)
    result['changed'].sort()
    result['verified'] = not any(result[key] for key in ('missing', 'extra', 'changed', 'errors'))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    scanning = commands.add_parser('scan')
    scanning.add_argument('--source', required=True)
    scanning.add_argument('--output', required=True)
    scanning.add_argument('--metadata-only', action='store_true')
    checking = commands.add_parser('verify')
    checking.add_argument('--manifest', required=True)
    checking.add_argument('--root', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'scan':
            source = safe_root(args.source)
            output = Path(args.output).resolve()
            if output.is_relative_to(source):
                raise ValueError('output_must_be_outside_source')
            if output.exists():
                raise ValueError('output_already_exists')
            result = scan(source, args.metadata_only)
            with output.open('x', encoding='utf-8') as stream:
                json.dump(result, stream, ensure_ascii=True, indent=2)
                stream.write('\n')
            print(json.dumps({'complete': result['complete'], 'mode': result['mode'],
                              'files_and_directories': len(result['entries']), 'errors': result['errors']}))
            return 0 if result['complete'] else 1
        manifest = json.loads(Path(args.manifest).read_text(encoding='utf-8'))
        result = verify(manifest, args.root)
        print(json.dumps(result, ensure_ascii=True))
        return 0 if result['verified'] else 1
    except (OSError, ValueError) as exc:
        print(json.dumps({'complete': False, 'error': str(exc) if isinstance(exc, ValueError) else type(exc).__name__}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
