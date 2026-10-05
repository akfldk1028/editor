import hashlib
import json

import pytest

from backend.app.modules.massing.archive import preserved_export
from backend.scripts.import_mass_archive import import_export


def test_archive_preserves_bytes_without_reading_original_after_import(tmp_path, monkeypatch):
    old = tmp_path / 'old'
    old.mkdir()
    complete = old / 'complete.json'
    complete.write_bytes(b'{"status":"complete"}')
    sha = hashlib.sha256(complete.read_bytes()).hexdigest()
    original = old / 'export'
    original.mkdir()
    (original / 'mesh.glb').write_bytes(b'preserved mesh')
    mesh_sha = hashlib.sha256((original / 'mesh.glb').read_bytes()).hexdigest()
    key = 'a' * 64
    receipt = {'request_hash': key, 'evidence': {str(complete): sha},
               'files': {'mesh.glb': mesh_sha},
               'result': {'request_hash': key, 'acceptance': 'not_evaluated',
                          'artifacts': [{'path': str(original / 'mesh.glb'), 'sha256': mesh_sha}]}}
    (original / 'receipt.json').write_text(json.dumps(receipt), encoding='utf-8')
    target = tmp_path / 'native' / 'mass-archive'
    import_export(original, target)
    original_receipt = (original / 'receipt.json').read_bytes()
    complete.unlink()
    (original / 'mesh.glb').unlink()
    monkeypatch.setenv('EDITOR_DESIGN_DATA_DIR', str(target.parent))
    request = {'completion_path': str(complete), 'completion_sha256': sha}
    result = preserved_export(request, key)
    assert result['acceptance'] == 'not_evaluated'
    assert result['artifacts'][0]['path'] == str(target / 'exports' / key / 'mesh.glb')
    assert (target / 'exports' / key / 'receipt.json').read_bytes() == original_receipt
    (target / 'exports' / key / 'mesh.glb').write_bytes(b'changed')
    with pytest.raises(ValueError, match='artifact set'):
        preserved_export(request, key)


def test_unknown_archive_request_is_not_silently_substituted(tmp_path, monkeypatch):
    monkeypatch.setenv('EDITOR_DESIGN_DATA_DIR', str(tmp_path))
    assert preserved_export({}, 'b' * 64) is None


def test_conflicting_source_identity_cannot_replace_existing_archive_index(tmp_path):
    source = tmp_path / 'export'
    source.mkdir()
    evidence = tmp_path / 'complete.json'
    target = tmp_path / 'native'
    def receipt(value, key):
        evidence.write_bytes(value)
        (source / 'receipt.json').write_text(json.dumps({
            'request_hash': key, 'files': {},
            'evidence': {str(evidence): hashlib.sha256(value).hexdigest()},
        }), encoding='utf-8')
    receipt(b'original evidence', 'a' * 64)
    import_export(source, target)
    unchanged = (target / 'manifest.json').read_bytes()
    receipt(b'different evidence', 'b' * 64)
    with pytest.raises(ValueError, match='conflicting bytes'):
        import_export(source, target)
    assert (target / 'manifest.json').read_bytes() == unchanged
    assert not (target / 'exports' / ('b' * 64)).exists()
    assert not list(target.glob('.manifest-*'))
