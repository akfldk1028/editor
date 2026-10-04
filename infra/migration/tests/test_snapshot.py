import importlib.util
import base64
import hashlib
import json
import os
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
