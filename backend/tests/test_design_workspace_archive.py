import json

import pytest

from backend.app.modules.design.artifacts import ArtifactArchive, ArtifactArchiveError, import_artifacts
from backend.app.modules.design.workspace_archive import WorkspaceArchive


def capture(tmp_path):
    source = tmp_path / 'source'
    pair = source / 'executed-masses' / 'run-a'
    pair.mkdir(parents=True)
    (pair / 'mass-01-abcdef.png').write_bytes(b'archived-image-test')
    (pair / 'mass-01-abcdef.png.passport.json').write_text(json.dumps({
        'mass_id': 'source-mass-1', 'program_hash': 'program-identity', 'geometry_hash': 'abcdef1234',
        'activation_graph': {'nodes': [], 'edges': []}, 'stages': [], 'final_hard_pass': False,
    }))
    destination = tmp_path / 'design'
    archive = ArtifactArchive(destination / 'artifacts')
    import_artifacts(archive, source, 'arr-maas-cache', dry_run=False)
    return WorkspaceArchive(destination)


def test_archive_preserves_identity_and_does_not_promote_old_results(tmp_path):
    store = capture(tmp_path)
    value = store.manifest('run-a')
    assert value['run_status'] == 'archived'
    assert value['numeric_status'] == 'not_reverified'
    assert value['masses'][0]['geometry_hash'] == 'abcdef1234'
    assert value['masses'][0]['hard_pass'] is False
    assert value['masses'][0]['far_pct'] is None
    assert store.passport('run-a', 1)['mass_id'] == 'source-mass-1'
    with pytest.raises(LookupError):
        store.passport('../run-a', 1)


def test_archive_rejects_tampered_bytes(tmp_path):
    store = capture(tmp_path)
    path = store.preview('run-a', 1)
    path.write_bytes(b'changed')
    with pytest.raises(ArtifactArchiveError):
        store.preview('run-a', 1)
