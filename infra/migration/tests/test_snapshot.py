import importlib.util
import base64
import hashlib
import json
import os
import stat
import struct
import subprocess
import sys
from pathlib import Path
import zipfile
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location('migration_snapshot', Path(__file__).parents[1] / 'snapshot.py')
snapshot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snapshot)


def test_roundtrip_preserves_hidden_empty_and_unicode(tmp_path):
    source = tmp_path / 'source'
    (source / '.git').mkdir(parents=True)
    (source / '.git' / 'HEAD').write_bytes(b'current dirty checkout')
    (source / 'empty').mkdir()
    (source / '공간 이름.txt').write_bytes('수정 중인 자료'.encode())
    archive = tmp_path / 'snapshot.zip'
    made = snapshot.create(source, archive)
    assert made['status'] == 'complete'
    assert snapshot.verify(archive)['status'] == 'complete'
    target = tmp_path / 'restored'
    assert snapshot.restore(archive, target)['status'] == 'complete'
    assert (target / '공간 이름.txt').read_bytes() == (source / '공간 이름.txt').read_bytes()
    assert (target / '.git' / 'HEAD').read_bytes() == b'current dirty checkout'
    assert (target / 'empty').is_dir()
    with pytest.raises(snapshot.SnapshotError):
        snapshot.restore(archive, target)
    with pytest.raises(snapshot.SnapshotError):
        snapshot.create(source, archive)


def test_destination_inside_source_refused(tmp_path):
    source = tmp_path / 'source'; source.mkdir()
    with pytest.raises(snapshot.SnapshotError):
        snapshot.create(source, source / 'backup.zip')


def test_changed_file_refused_and_partial_archive_removed(tmp_path, monkeypatch):
    source = tmp_path / 'source'; source.mkdir()
    item = source / 'file'; item.write_bytes(b'first')
    original = snapshot._copy_file
    def changing(*args, **kwargs):
        result = original(*args, **kwargs)
        item.write_bytes(b'second')
        return result
    monkeypatch.setattr(snapshot, '_copy_file', changing)
    archive = tmp_path / 'backup.zip'
    with pytest.raises(snapshot.SnapshotError, match='changed'):
        snapshot.create(source, archive)
    assert not archive.exists()


def test_windows_handle_ctime_need_not_equal_path_ctime(tmp_path, monkeypatch):
    source = tmp_path / 'source'; source.mkdir(); (source / 'a').write_bytes(b'a')
    original = snapshot.os.fstat
    def different_ctime(fd):
        info = original(fd)
        values = {name: getattr(info, name) for name in dir(info) if name.startswith('st_')}
        values['st_ctime_ns'] += 1
        return SimpleNamespace(**values)
    monkeypatch.setattr(snapshot.os, 'fstat', different_ctime)
    assert snapshot.create(source, tmp_path / 'backup.zip')['status'] == 'complete'


def test_windows_directory_allocation_size_is_not_file_content(monkeypatch):
    monkeypatch.setattr(snapshot, '_windows', lambda: True)
    base = dict(st_dev=1, st_ino=2, st_mode=stat.S_IFDIR | 0o755, st_size=65536,
                st_mtime_ns=3, st_ctime_ns=4, st_file_attributes=16)
    assert snapshot._signature(SimpleNamespace(**base)) == snapshot._signature(SimpleNamespace(**{**base, 'st_size': 0}))
    for mode in (stat.S_IFREG, stat.S_IFLNK):
        left = SimpleNamespace(**{**base, 'st_mode': mode})
        right = SimpleNamespace(**{**base, 'st_mode': mode, 'st_size': 0})
        assert snapshot._signature(left) != snapshot._signature(right)
    changed = SimpleNamespace(**{**base, 'st_mtime_ns': 5})
    assert snapshot._signature(SimpleNamespace(**base)) != snapshot._signature(changed)


def test_tree_change_reports_exact_added_path(tmp_path, monkeypatch):
    source = tmp_path / 'source'; source.mkdir(); (source / 'a').write_bytes(b'a')
    original = snapshot._copy_file
    def add_file(*args):
        result = original(*args)
        (source / 'appeared.txt').write_bytes(b'new')
        return result
    monkeypatch.setattr(snapshot, '_copy_file', add_file)
    with pytest.raises(snapshot.SnapshotError, match='appeared.txt'):
        snapshot.create(source, tmp_path / 'bad.zip')


def test_linked_root_ancestor_refused(tmp_path):
    actual = tmp_path / 'actual'; (actual / 'source').mkdir(parents=True)
    alias = tmp_path / 'alias'
    try: alias.symlink_to(actual, target_is_directory=True)
    except OSError: pytest.skip('OS does not allow test symlink')
    with pytest.raises(snapshot.SnapshotError): snapshot.create(alias / 'source', tmp_path / 'backup.zip')
    with pytest.raises(snapshot.SnapshotError): snapshot.create(actual / 'source', alias / 'backup.zip')


def test_unsupported_lx_link_preserves_raw_reparse_bytes_without_following(monkeypatch):
    raw = b'\x1d\x00\x00\xa0\x0a\x00\x00\x00\x02\x00\x00\x00python'
    monkeypatch.setattr(snapshot.os, 'readlink', lambda path: (_ for _ in ()).throw(ValueError('not a symbolic link')))
    seen = []
    monkeypatch.setattr(snapshot, '_read_reparse_data', lambda path: seen.append(path) or raw)
    info = SimpleNamespace(st_reparse_tag=2684354589, st_file_attributes=1024)
    result = snapshot._link_metadata(Path('never-open-target'), info)
    assert seen == [Path('never-open-target')]
    assert result['target'] is None
    assert 'ValueError' in result['readlink_error']
    assert base64.b64decode(result['reparse_data_base64']) == raw
    assert result['reparse_data_sha256'] == hashlib.sha256(raw).hexdigest()


def test_unreadable_reparse_metadata_is_a_failure(monkeypatch):
    monkeypatch.setattr(snapshot.os, 'readlink', lambda path: (_ for _ in ()).throw(ValueError('unsupported')))
    monkeypatch.setattr(snapshot, '_read_reparse_data', lambda path: (_ for _ in ()).throw(OSError('access denied')))
    with pytest.raises(OSError):
        snapshot._link_metadata(Path('never-open-target'), SimpleNamespace(st_reparse_tag=2684354589, st_file_attributes=1024))


def test_link_target_never_archived_or_restored(tmp_path):
    source = tmp_path / 'source'; source.mkdir()
    outside = tmp_path / 'outside'; outside.mkdir()
    (outside / 'private').write_bytes(b'not part of tree')
    try:
        (source / 'link').symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('OS does not allow creating symlink for test')
    archive = tmp_path / 'backup.zip'
    assert snapshot.create(source, archive)['status'] == 'incomplete_links'
    with zipfile.ZipFile(archive) as z:
        assert not any('private' in name for name in z.namelist())
        manifest = json.loads(z.read('snapshot-manifest.json'))
        assert manifest['entries'][0]['kind'] == 'link'
    target = tmp_path / 'restored'
    assert snapshot.restore(archive, target)['status'] == 'incomplete_links'
    assert not (target / 'link').exists()


@pytest.mark.parametrize('bad', ['../escape', '/absolute', 'C:/drive', '//server/share', 'a\\b', 'CON', 'file:stream', 'trailing.'])
def test_unsafe_archive_paths_refused_before_creating_target(tmp_path, bad):
    archive = tmp_path / 'bad.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('snapshot-manifest.json', json.dumps({'schema': 'ace.snapshot.v1', 'entries': []}))
        z.writestr('data/' + bad, b'x')
    target = tmp_path / 'target'
    with pytest.raises(snapshot.SnapshotError):
        snapshot.restore(archive, target)
    assert not target.exists()


def test_duplicate_case_and_hash_tamper_refused(tmp_path):
    source = tmp_path / 'source'; source.mkdir(); (source / 'A').write_bytes(b'a')
    archive = tmp_path / 'good.zip'; snapshot.create(source, archive)
    with zipfile.ZipFile(archive) as z:
        records = [(i.filename, z.read(i)) for i in z.infolist()]
    for mode in ('case', 'hash'):
        bad = tmp_path / (mode + '.zip')
        with zipfile.ZipFile(bad, 'w') as z:
            for name, data in records:
                z.writestr(name, b'b' if mode == 'hash' and name == 'data/A' else data)
            if mode == 'case': z.writestr('data/a', b'a')
        with pytest.raises(snapshot.SnapshotError): snapshot.verify(bad)


def raw_row(name, tag, payload, directory=False):
    raw = struct.pack('<IHH', tag, len(payload), 0) + payload
    return {'path': name, 'kind': 'link', 'target': None, 'reparse_tag': tag,
            'signature': [0, 0, stat.S_IFLNK, 0, 0, 0, 1024 | (16 if directory else 0)],
            'reparse_data_base64': base64.b64encode(raw).decode(),
            'reparse_data_sha256': hashlib.sha256(raw).hexdigest()}


@pytest.mark.skipif(os.name != 'nt', reason='Windows raw reparse restoration')
def test_opt_in_restores_all_supported_links_and_never_follows_targets(tmp_path, monkeypatch):
    source = tmp_path / 'source'; source.mkdir()
    outside = tmp_path / 'outside'; outside.mkdir()
    (outside / 'untouched').write_bytes(b'private external target')
    subprocess.run(['cmd', '/c', 'mklink', '/J', str(source / 'junction'), str(outside)], check=True, capture_output=True)
    for name, directory in [('file-link', False), ('directory-link', True)]:
        target = ('missing-directory' if directory else 'missing-file').encode('utf-16-le')
        payload = struct.pack('<HHHHI', 0, len(target), 0, len(target), 1) + target
        snapshot._restore_reparse(source / name, raw_row(name, 0xA000000C, payload, directory))
    snapshot._restore_reparse(source / 'linux-link', raw_row('linux-link', 0xA000001D, struct.pack('<I', 2) + b'python3'))
    (source / 'regular').write_bytes(b'regular first')
    archive = tmp_path / 'links.zip'
    assert snapshot.create(source, archive)['status'] == 'incomplete_links'
    target = tmp_path / 'restored'
    original = snapshot._restore_reparse
    def assert_regular_files_first(path, row):
        assert (target / 'regular').read_bytes() == b'regular first'
        return original(path, row)
    monkeypatch.setattr(snapshot, '_restore_reparse', assert_regular_files_first)
    result = snapshot.restore(archive, target, restore_reparse=True)
    monkeypatch.setattr(snapshot, '_restore_reparse', original)
    assert result['status'] == 'complete'
    assert result['restored_links'] == 4
    assert result['unresolved_links'] == []
    assert snapshot.verify(archive, restored_root=target)['status'] == 'complete'
    for name in ('junction', 'file-link', 'directory-link', 'linux-link'):
        assert snapshot._read_reparse_data(target / name) == snapshot._read_reparse_data(source / name)
    assert (target / 'directory-link').lstat().st_file_attributes & 16
    assert (outside / 'untouched').read_bytes() == b'private external target'
    assert not (target / 'untouched').exists()
    with pytest.raises(snapshot.SnapshotError):
        snapshot._restore_reparse(target / 'regular', raw_row('regular', 0xA000001D, struct.pack('<I', 2) + b'python3'))
    (target / 'regular').write_bytes(b'tampered')
    with pytest.raises(snapshot.SnapshotError, match='hash'):
        snapshot.verify(archive, restored_root=target)
    cli_target = tmp_path / 'cli-restored'
    script = str(Path(__file__).parents[1] / 'snapshot.py')
    process = subprocess.run([sys.executable, script, 'restore', str(archive), str(cli_target), '--restore-reparse'], capture_output=True)
    assert process.returncode == 0, process.stdout
    assert json.loads(process.stdout)['restored_links'] == 4
    process = subprocess.run([sys.executable, script, 'verify', str(archive), '--root', str(cli_target)], capture_output=True)
    assert process.returncode == 0, process.stdout


def test_link_parent_collision_refused_before_restoration(tmp_path):
    rows = [raw_row('link', 0xA000001D, struct.pack('<I', 2) + b'python3'),
            {'path': 'link/child', 'kind': 'directory'}]
    archive = tmp_path / 'collision.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr(snapshot.MANIFEST, json.dumps({'schema': snapshot.SCHEMA, 'entries': rows}))
    target = tmp_path / 'restore'
    with pytest.raises(snapshot.SnapshotError, match='parent collision'):
        snapshot.restore(archive, target, restore_reparse=True)
    assert not target.exists()


@pytest.mark.parametrize('damage', ['tag', 'hash', 'size', 'signature', 'unsupported'])
def test_bad_reparse_record_refused_before_creating_restore_root(tmp_path, damage):
    row = raw_row('bad-link', 0xA000001D, struct.pack('<I', 2) + b'python3')
    if damage == 'tag': row['reparse_tag'] = 0xA0000003
    if damage == 'hash': row['reparse_data_sha256'] = '0' * 64
    if damage == 'signature': row['signature'] = []
    if damage == 'size':
        raw = base64.b64decode(row['reparse_data_base64']) + b'extra'
        row.update(reparse_data_base64=base64.b64encode(raw).decode(), reparse_data_sha256=hashlib.sha256(raw).hexdigest())
    if damage == 'unsupported': row = raw_row('bad-link', 0xA0000099, b'unsupported')
    archive = tmp_path / 'bad.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr(snapshot.MANIFEST, json.dumps({'schema': snapshot.SCHEMA, 'entries': [row]}))
    target = tmp_path / 'target'
    with pytest.raises(snapshot.SnapshotError): snapshot.restore(archive, target, restore_reparse=True)
    assert not target.exists()


def test_reparse_restore_flag_rejected_on_other_platforms(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot, '_windows', lambda: False)
    with pytest.raises(snapshot.SnapshotError, match='Windows'):
        snapshot.restore(tmp_path / 'unused.zip', tmp_path / 'target', restore_reparse=True)
    assert not (tmp_path / 'target').exists()
