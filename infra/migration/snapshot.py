"""Non-destructive, stored-ZIP snapshots. Link targets are never followed.

Exit 0: verified complete regular-file snapshot/restore; 2: recorded links require
separate restoration; 1: failure. Raw Windows link restoration is explicit opt-in.
This is not a live-database consistency backup.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
import sys
import zipfile

MANIFEST = 'snapshot-manifest.json'
SCHEMA = 'ace.snapshot.v1'
CHUNK = 1024 * 1024


class SnapshotError(ValueError):
    pass


def _windows():
    return os.name == 'nt'


def _validated_reparse(row, for_restore=False):
    try:
        raw = base64.b64decode(row['reparse_data_base64'], validate=True)
    except (KeyError, TypeError, ValueError) as exc:
        raise SnapshotError('raw reparse metadata missing or invalid') from exc
    if (not 8 <= len(raw) <= 16384 or hashlib.sha256(raw).hexdigest() != row.get('reparse_data_sha256')
            or struct.unpack_from('<I', raw)[0] != row.get('reparse_tag')
            or struct.unpack_from('<H', raw, 4)[0] + 8 != len(raw)):
        raise SnapshotError('reparse metadata tag/size/hash mismatch')
    if for_restore:
        if row['reparse_tag'] not in (0xA0000003, 0xA000000C, 0xA000001D):
            raise SnapshotError('unsupported reparse restoration tag')
        signature = row.get('signature')
        if (not isinstance(signature, list) or len(signature) != 7
                or type(signature[6]) is not int or not signature[6] & 1024):
            raise SnapshotError('Windows reparse directory attributes missing')
    return raw


def _restore_reparse(path, row):
    if not _windows():
        raise SnapshotError('raw reparse restoration requires Windows')
    raw = _validated_reparse(row, for_restore=True)
    path = _plain_directory(Path(path).parent) / Path(path).name
    if os.path.lexists(path):
        raise SnapshotError('reparse restore path must not already exist')
    directory = bool(row['signature'][6] & 16)
    if directory:
        path.mkdir()
    else:
        with path.open('xb'):
            pass
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    control = kernel.DeviceIoControl
    control.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                       ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    control.restype = wintypes.BOOL
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]; close.restype = wintypes.BOOL
    handle = create(str(path), 0x40000000, 7, None, 3, 0x00200000 | 0x02000000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        buffer = ctypes.create_string_buffer(raw)
        returned = wintypes.DWORD()
        if not control(handle, 0x000900A4, buffer, len(raw), None, 0, ctypes.byref(returned), None):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        close(handle)
    if _read_reparse_data(path) != raw or bool(path.lstat().st_file_attributes & 16) != directory:
        raise SnapshotError('restored reparse bytes or directory flag differ')


def _safe_path(value):
    if not isinstance(value, str) or not value or '\\' in value or ':' in value or value.startswith('/'):
        raise SnapshotError('unsafe archive path')
    for part in value.split('/'):
        if (part in ('', '.', '..') or part.endswith(('.', ' '))
                or any(ord(c) < 32 or c in '<>"|?*' for c in part)
                or re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])', part.split('.')[0])):
            raise SnapshotError('unsafe archive path')
    return value


def _is_link(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 1024)


def _read_reparse_data(path):
    """Read the link itself, including LX_SYMLINK unsupported by os.readlink."""
    if os.name != 'nt':
        raise SnapshotError('raw reparse records require Windows')
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    control = kernel.DeviceIoControl
    control.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                       ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    control.restype = wintypes.BOOL
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]; close.restype = wintypes.BOOL
    # Zero desired access + OPEN_REPARSE_POINT never opens the target.
    handle = create(str(path), 0, 7, None, 3, 0x00200000 | 0x02000000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        buffer = ctypes.create_string_buffer(16 * 1024)
        returned = wintypes.DWORD()
        if not control(handle, 0x000900A8, None, 0, buffer, len(buffer), ctypes.byref(returned), None):
            raise ctypes.WinError(ctypes.get_last_error())
        return buffer.raw[:returned.value]
    finally:
        close(handle)


def _link_metadata(path, info):
    result = {'reparse_tag': getattr(info, 'st_reparse_tag', None)}
    try:
        result['target'] = os.readlink(path)
    except (OSError, ValueError) as exc:
        if not getattr(info, 'st_file_attributes', 0) & 1024:
            raise
        result.update(target=None, readlink_error=type(exc).__name__ + ': ' + str(exc))
    if getattr(info, 'st_file_attributes', 0) & 1024:
        raw = _read_reparse_data(path)
        if len(raw) < 8 or struct.unpack_from('<I', raw)[0] != result['reparse_tag']:
            raise SnapshotError('reparse tag changed or record incomplete')
        result.update(reparse_data_base64=base64.b64encode(raw).decode('ascii'),
                      reparse_data_sha256=hashlib.sha256(raw).hexdigest())
    return result


def _signature(info):
    # Windows may report directory allocation size or zero for the same NTFS directory.
    size = 0 if _windows() and stat.S_ISDIR(info.st_mode) and not _is_link(info) else info.st_size
    return (info.st_dev, info.st_ino, info.st_mode, size, info.st_mtime_ns,
            getattr(info, 'st_ctime_ns', 0), getattr(info, 'st_file_attributes', 0))


def _plain_directory(path):
    path = Path(os.path.abspath(path))
    for ancestor in reversed([path, *path.parents]):
        info = ancestor.lstat()
        if _is_link(info) or not stat.S_ISDIR(info.st_mode):
            raise SnapshotError('directory ancestry must not contain links/reparse points')
    return path


def _inventory(root):
    rows = []
    stack = [root]
    while stack:
        directory = stack.pop()
        info = directory.lstat()
        if _is_link(info) or not stat.S_ISDIR(info.st_mode):
            raise SnapshotError('source directory changed into a link or non-directory')
        with os.scandir(directory) as iterator:
            children = sorted(iterator, key=lambda e: e.name)
        for child in children:
            path = Path(child.path)
            info = path.lstat()
            relative = _safe_path(path.relative_to(root).as_posix())
            row = {'path': relative, 'mode': stat.S_IMODE(info.st_mode),
                   'mtime_ns': info.st_mtime_ns, 'signature': list(_signature(info))}
            if _is_link(info):
                row.update(kind='link', **_link_metadata(path, info))
            elif stat.S_ISDIR(info.st_mode):
                row['kind'] = 'directory'
                stack.append(path)
            elif stat.S_ISREG(info.st_mode):
                row.update(kind='file', size=info.st_size)
            else:
                raise SnapshotError('unsupported source file kind: ' + relative)
            rows.append(row)
    rows.sort(key=lambda row: row['path'])
    _validate_rows(rows, require_hash=False)
    return rows


def _copy_file(path, row, archive):
    before = path.lstat()
    if _is_link(before) or list(_signature(before)) != row['signature']:
        raise SnapshotError('source file changed before read: ' + row['path'])
    digest = hashlib.sha256()
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        # Windows path-stat and handle-stat can report different creation times.
        identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
        if _is_link(opened) or not stat.S_ISREG(opened.st_mode) or identity(opened) != identity(before):
            raise SnapshotError('source file changed while opening: ' + row['path'])
        with archive.open('data/' + row['path'], 'w', force_zip64=True) as output:
            while block := stream.read(CHUNK):
                digest.update(block)
                output.write(block)
        if _signature(os.fstat(stream.fileno())) != _signature(opened):
            raise SnapshotError('source file changed during read: ' + row['path'])
        stream.seek(0)
        second = hashlib.file_digest(stream, 'sha256').hexdigest()
    if second != digest.hexdigest() or _signature(path.lstat()) != _signature(before):
        raise SnapshotError('source file changed after read: ' + row['path'])
    return digest.hexdigest()


def _result(rows, links_restored=False):
    links = [row for row in rows if row['kind'] == 'link']
    return {'schema': SCHEMA, 'status': 'incomplete_links' if links and not links_restored else 'complete',
            'files': sum(row['kind'] == 'file' for row in rows),
            'directories': sum(row['kind'] == 'directory' for row in rows),
            'bytes': sum(row.get('size', 0) for row in rows),
            'restored_links': len(links) if links_restored else 0,
            'unresolved_links': [] if links_restored else links}


def _tree_changes(before, after, limit=8):
    old, new = ({row['path']: row for row in rows} for rows in (before, after))
    changes = []
    for path in sorted(old.keys() | new.keys()):
        if old.get(path) == new.get(path):
            continue
        if path not in old or path not in new:
            changes.append({'path': path, 'change': 'added' if path not in old else 'removed'})
        else:
            changes.append({'path': path, 'fields': {key: {'before': old[path].get(key),
                'after': new[path].get(key)} for key in old[path].keys() | new[path].keys()
                if old[path].get(key) != new[path].get(key)}})
        if len(changes) >= limit:
            break
    return changes


def create(source, destination):
    source, destination = Path(source), Path(destination)
    source = _plain_directory(source)
    destination = _plain_directory(destination.parent) / destination.name
    if destination.is_relative_to(source):
        raise SnapshotError('archive destination must be outside source')
    if os.path.lexists(destination):
        raise SnapshotError('archive already exists')
    rows = _inventory(source)
    baseline = json.dumps(rows, sort_keys=True)
    created = False
    try:
        with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
            created = True
            for row in rows:
                if row['kind'] == 'file':
                    row['sha256'] = _copy_file(source / row['path'], row, archive)
            after = _inventory(source)
            if json.dumps(after, sort_keys=True) != baseline:
                changes = _tree_changes(json.loads(baseline), after)
                raise SnapshotError('source tree changed during snapshot; first differences: ' +
                                    json.dumps(changes, ensure_ascii=True, sort_keys=True))
            archive.writestr(MANIFEST, json.dumps({'schema': SCHEMA, 'source_root': str(source),
                'link_policy': 'record_only', 'entries': rows}, ensure_ascii=False, allow_nan=False))
        return _result(rows)
    except Exception as exc:
        if created:
            destination.unlink()
        if isinstance(exc, SnapshotError):
            raise
        raise SnapshotError('snapshot failed: ' + str(exc)) from exc


def _validate_rows(rows, require_hash=True):
    if not isinstance(rows, list):
        raise SnapshotError('manifest entries must be a list')
    names = {}
    for row in rows:
        if not isinstance(row, dict):
            raise SnapshotError('invalid manifest row')
        name = _safe_path(row.get('path'))
        key = name.casefold()
        if key in names or row.get('kind') not in ('file', 'directory', 'link'):
            raise SnapshotError('duplicate case-insensitive path or invalid kind')
        names[key] = row['kind']
        if row['kind'] == 'file' and (type(row.get('size')) is not int or row['size'] < 0
                or (require_hash and not re.fullmatch('[0-9a-f]{64}', row.get('sha256', '')))):
            raise SnapshotError('invalid file size/hash')
        if row['kind'] == 'link':
            if 'reparse_data_base64' in row:
                _validated_reparse(row)
            elif not isinstance(row.get('target'), str):
                raise SnapshotError('link target metadata missing')
    for name in names:
        parts = name.split('/')
        for index in range(1, len(parts)):
            if names.get('/'.join(parts[:index])) != 'directory':
                raise SnapshotError('missing directory or file/link parent collision')


def _verified_manifest(archive):
    infos = archive.infolist()
    names = set()
    for info in infos:
        name = _safe_path(info.filename)
        if name.casefold() in names or info.compress_type != zipfile.ZIP_STORED:
            raise SnapshotError('duplicate archive path or unsupported compression')
        names.add(name.casefold())
        if stat.S_ISLNK(info.external_attr >> 16) or info.is_dir():
            raise SnapshotError('archive links/directories must be manifest records only')
    if MANIFEST.casefold() not in names:
        raise SnapshotError('manifest missing')
    manifest = json.loads(archive.read(MANIFEST))
    if not isinstance(manifest, dict) or manifest.get('schema') != SCHEMA:
        raise SnapshotError('unsupported manifest')
    rows = manifest.get('entries')
    _validate_rows(rows)
    expected = {MANIFEST} | {'data/' + row['path'] for row in rows if row['kind'] == 'file'}
    if {info.filename for info in infos} != expected:
        raise SnapshotError('archive contents differ from manifest')
    for row in rows:
        if row['kind'] != 'file':
            continue
        info = archive.getinfo('data/' + row['path'])
        if info.file_size != row['size']:
            raise SnapshotError('file size differs from manifest')
        with archive.open(info) as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != row['sha256']:
            raise SnapshotError('file hash differs from manifest')
    return manifest


def _verify_restored(rows, root):
    root = _plain_directory(root)
    observed = {row['path']: row for row in _inventory(root)}
    if set(observed) != {row['path'] for row in rows}:
        raise SnapshotError('restored tree paths differ from manifest')
    for row in rows:
        actual = observed[row['path']]
        if actual['kind'] != row['kind']:
            raise SnapshotError('restored kind differs: ' + row['path'])
        if row['kind'] == 'file':
            path = root / row['path']
            before = path.lstat()
            flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
            with os.fdopen(os.open(path, flags), 'rb') as stream:
                opened = os.fstat(stream.fileno())
                if _is_link(opened) or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                    raise SnapshotError('restored file changed while opening')
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                if _signature(os.fstat(stream.fileno())) != _signature(opened):
                    raise SnapshotError('restored file changed while verifying')
            if (actual['size'] != row['size'] or digest != row['sha256']
                    or _signature(path.lstat()) != _signature(before)):
                raise SnapshotError('restored file size/hash mismatch: ' + row['path'])
        elif row['kind'] == 'link':
            for key in ('reparse_tag', 'reparse_data_base64', 'reparse_data_sha256', 'target'):
                if actual.get(key) != row.get(key):
                    raise SnapshotError('restored link metadata differs: ' + row['path'])
            if bool(actual['signature'][6] & 16) != bool(row['signature'][6] & 16):
                raise SnapshotError('restored link directory flag differs')
    return _result(rows, links_restored=True)


def verify(archive_path, restored_root=None):
    try:
        with zipfile.ZipFile(archive_path) as archive:
            rows = _verified_manifest(archive)['entries']
            return _verify_restored(rows, restored_root) if restored_root is not None else _result(rows)
    except Exception as exc:
        if isinstance(exc, SnapshotError): raise
        raise SnapshotError('verification failed: ' + str(exc)) from exc


def restore(archive_path, target, *, restore_reparse=False):
    if restore_reparse and not _windows():
        raise SnapshotError('raw reparse restoration requires Windows')
    target = Path(target)
    target = _plain_directory(target.parent) / target.name
    if os.path.lexists(target):
        raise SnapshotError('restore target must not exist, even if empty')
    try:
        with zipfile.ZipFile(archive_path) as archive:
            rows = _verified_manifest(archive)['entries']
            if restore_reparse:
                for row in rows:
                    if row['kind'] == 'link':
                        _validated_reparse(row, for_restore=True)
            target.mkdir()
            for row in sorted(rows, key=lambda row: (row['path'].count('/'), row['path'])):
                path = target / row['path']
                if row['kind'] == 'directory':
                    path.mkdir()
                elif row['kind'] == 'file':
                    with archive.open('data/' + row['path']) as stream, path.open('xb') as output:
                        digest = hashlib.sha256()
                        while block := stream.read(CHUNK):
                            output.write(block); digest.update(block)
                    if digest.hexdigest() != row['sha256']:
                        raise SnapshotError('archive changed during restore')
            if restore_reparse:
                for row in rows:
                    if row['kind'] == 'link':
                        _restore_reparse(target / row['path'], row)
            # Manifest parents are plain directories; no operation enters a link.
            for row in sorted(rows, key=lambda row: row['path'].count('/'), reverse=True):
                if row['kind'] != 'link' and type(row.get('mtime_ns')) is int:
                    os.utime(target / row['path'], ns=(row['mtime_ns'], row['mtime_ns']))
            return _verify_restored(rows, target) if restore_reparse else _result(rows)
    except Exception as exc:
        if isinstance(exc, SnapshotError): raise
        raise SnapshotError('restore failed; target may contain partial files: ' + str(exc)) from exc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('create'); p.add_argument('source'); p.add_argument('archive')
    p = commands.add_parser('verify'); p.add_argument('archive'); p.add_argument('--root')
    p = commands.add_parser('restore'); p.add_argument('archive'); p.add_argument('target')
    p.add_argument('--restore-reparse', action='store_true')
    args = parser.parse_args()
    try:
        result = (create(args.source, args.archive) if args.command == 'create' else
                  verify(args.archive, restored_root=args.root) if args.command == 'verify' else
                  restore(args.archive, args.target, restore_reparse=args.restore_reparse))
        print(json.dumps(result, ensure_ascii=True))
        return 2 if result['status'] == 'incomplete_links' else 0
    except (ValueError, OSError) as exc:
        print(json.dumps({'status': 'failed', 'error': str(exc)}, ensure_ascii=True))
        return 1


if __name__ == '__main__':
    sys.exit(main())
