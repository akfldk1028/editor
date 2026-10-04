from io import BytesIO
import json
import shutil
import sqlite3
from unittest.mock import patch

from PIL import Image
import pytest

from backend.app.modules.design.artifacts import ArtifactArchive, import_artifacts
from backend.app.modules.design.execution_catalog import ExecutionCatalog, CatalogUnavailable


def capture(tmp_path, namespace='arr-maas-cache', group='single-executions/run-one'):
    source=tmp_path/namespace;folder=source/group;folder.mkdir(parents=True)
    (folder/'execution.json').write_text(json.dumps({'execution_id':'run-one','status':'complete',
        'source_run_id':'missing-original','source_mass_index':1,'private_path':'D:/private'}))
    image=BytesIO();Image.new('RGB',(2,2)).save(image,format='PNG')
    (folder/'mass.png').write_bytes(image.getvalue())
    (folder/'mass.png.passport.json').write_text('{"original":"bytes"}')
    (folder/'unknown.tmp').write_text('opaque')
    root=tmp_path/'editor';archive=ArtifactArchive(root/'artifacts')
    import_artifacts(archive,source,namespace,dry_run=False)
    return root,source,archive


def test_unregistered_reads_are_empty_and_do_not_create_storage(tmp_path):
    root=tmp_path/'empty';catalog=ExecutionCatalog(root)
    assert catalog.list_executions()==[]
    assert catalog.project_executions('a','p')==[]
    assert not root.exists()


def test_pinned_catalog_survives_additive_snapshot_and_offline_source(tmp_path):
    root,source,archive=capture(tmp_path);catalog=ExecutionCatalog(root)
    first=catalog.register('arr-maas-cache')
    row=catalog.list_executions()[0]
    assert row['execution_state']=='archived' and row['has_preview'] and row['has_passport']
    assert 'private' not in json.dumps(row)
    assert catalog.register('arr-maas-cache')==first
    files=catalog.artifacts(row['catalog_id']);preview=next(f for f in files if f['role']=='preview')
    assert not any('path' in key for f in files for key in f)
    (source/'single-executions/run-one/program.json').write_text('{}')
    import_artifacts(archive,source,'arr-maas-cache',dry_run=False)
    catalog.register('arr-maas-cache')
    assert len(catalog.list_executions())==2
    assert len(catalog.artifacts(row['catalog_id']))==3
    shutil.rmtree(source)
    path,metadata=catalog.resolve_artifact(row['catalog_id'],preview['artifact_id'])
    assert path.read_bytes().startswith(b'\x89PNG') and metadata['inline'] is True


def test_project_attachments_are_isolated_idempotent_and_persistent(tmp_path):
    root,_,_=capture(tmp_path);catalog=ExecutionCatalog(root);catalog.register('arr-maas-cache')
    identifier=catalog.list_executions()[0]['catalog_id']
    catalog.attach('a','p','scene',2,identifier);catalog.attach('a','p','scene',2,identifier)
    reopened=ExecutionCatalog(root)
    assert len(reopened.project_executions('a','p'))==1
    assert reopened.project_executions('b','p')==[]
    assert not reopened.is_attached('a','other',identifier)
    with pytest.raises(ValueError): reopened.attach('a','p','changed',3,identifier)


def test_tampered_png_and_unknown_artifacts_fail_explicitly(tmp_path):
    root,_,_=capture(tmp_path);catalog=ExecutionCatalog(root);catalog.register('arr-maas-cache')
    identifier=catalog.list_executions()[0]['catalog_id']
    artifact=next(f for f in catalog.artifacts(identifier) if f['inline'])
    (root/'artifacts/blobs'/artifact['sha256']).write_bytes(b'bad')
    with pytest.raises(CatalogUnavailable):catalog.resolve_artifact(identifier,artifact['artifact_id'])
    with pytest.raises(LookupError):catalog.resolve_artifact(identifier,'0'*64)


def test_invalid_image_with_valid_hash_cannot_render_inline(tmp_path):
    root,source,archive=capture(tmp_path)
    (source/'single-executions/run-one/mass.png').write_bytes(b'not a png')
    root=tmp_path/'invalid-editor'
    import_artifacts(ArtifactArchive(root/'artifacts'),source,'arr-maas-cache',dry_run=False)
    catalog=ExecutionCatalog(root);catalog.register('arr-maas-cache')
    row=catalog.list_executions()[0]
    inline=[item for item in catalog.artifacts(row['catalog_id']) if item['inline']]
    assert len(inline)==1
    with pytest.raises(CatalogUnavailable):catalog.resolve_artifact(row['catalog_id'],inline[0]['artifact_id'])


@pytest.mark.parametrize('value',['not json','[]','{"catalog_id":"bad"}'])
def test_corrupt_summary_is_unavailable(tmp_path,value):
    root,_,_=capture(tmp_path);catalog=ExecutionCatalog(root);catalog.register('arr-maas-cache')
    with sqlite3.connect(catalog.path) as db:db.execute('UPDATE executions SET summary_json=?',(value,))
    with pytest.raises(CatalogUnavailable):catalog.list_executions()


def test_metadata_is_bounded_and_group_identity_is_preserved(tmp_path):
    root,source,_=capture(tmp_path)
    folder=source/'single-executions/run-one'
    (folder/'execution.json').write_text(json.dumps({'execution_id':'other','status':'D:/private','source_run_id':'D:/private'}))
    root=tmp_path/'safe-editor'
    import_artifacts(ArtifactArchive(root/'artifacts'),source,'arr-maas-cache',dry_run=False)
    catalog=ExecutionCatalog(root);catalog.register('arr-maas-cache')
    row=catalog.list_executions()[0]
    assert row['execution_id']=='run-one' and row['metadata_status']=='metadata_unavailable'
    assert row['source_status'] is None and 'replay_reference' not in row
    (folder/'execution.json').write_text('x'*(1024*1024+1))
    root=tmp_path/'large-editor'
    import_artifacts(ArtifactArchive(root/'artifacts'),source,'arr-maas-cache',dry_run=False)
    catalog=ExecutionCatalog(root);catalog.register('arr-maas-cache')
    assert catalog.list_executions()[0]['metadata_status']=='metadata_unavailable'


def test_unrecognized_persisted_role_cannot_be_served(tmp_path):
    root,_,_=capture(tmp_path);catalog=ExecutionCatalog(root);catalog.register('arr-maas-cache')
    row=catalog.list_executions()[0];item=catalog.artifacts(row['catalog_id'])[0]
    item['role']='arbitrary'
    with sqlite3.connect(catalog.path) as db:
        db.execute('UPDATE artifacts SET metadata_json=? WHERE artifact_id=?',(json.dumps(item),item['artifact_id']))
    with pytest.raises(CatalogUnavailable):catalog.resolve_artifact(row['catalog_id'],item['artifact_id'])


def test_linked_blob_is_rejected_and_reads_do_not_change_storage(tmp_path):
    root,_,_=capture(tmp_path);catalog=ExecutionCatalog(root);catalog.register('arr-maas-cache')
    row=catalog.list_executions()[0];items=catalog.artifacts(row['catalog_id'])
    before={path:path.read_bytes() for path in root.rglob('*') if path.is_file()}
    for item in items:catalog.resolve_artifact(row['catalog_id'],item['artifact_id'])
    catalog.get_execution(row['catalog_id']);catalog.list_executions()
    assert before=={path:path.read_bytes() for path in root.rglob('*') if path.is_file()}
    blob=root/'artifacts/blobs'/items[0]['sha256']
    # Link detection is shared with the archive; emulate Windows junction detection without admin privileges.
    with patch('backend.app.modules.design.artifacts._linked',side_effect=lambda path:path==blob):
        with pytest.raises(CatalogUnavailable):catalog.resolve_artifact(row['catalog_id'],items[0]['artifact_id'])


def test_missing_manifest_keeps_group_identity_and_available_files(tmp_path):
    root,source,_=capture(tmp_path)
    (source/'single-executions/run-one/execution.json').unlink()
    root=tmp_path/'missing-editor'
    import_artifacts(ArtifactArchive(root/'artifacts'),source,'arr-maas-cache',dry_run=False)
    catalog=ExecutionCatalog(root);catalog.register('arr-maas-cache')
    row=catalog.list_executions()[0]
    assert row['execution_id']=='run-one' and row['metadata_status']=='missing' and row['has_preview']


def test_both_namespaces_and_incomplete_groups(tmp_path):
    root,_,_=capture(tmp_path);catalog=ExecutionCatalog(root);catalog.register('arr-maas-cache')
    source=tmp_path/'portfolio';folder=source/'portfolio-one';folder.mkdir(parents=True)
    (folder/'maas-run-state.json').write_text('{"status":"failed"}')
    (folder/'maas-book-exact-geometry-artifacts.json').write_text('{}')
    import_artifacts(ArtifactArchive(root/'artifacts'),source,'arr-design-executions',dry_run=False)
    catalog.register('arr-design-executions')
    row=next(r for r in catalog.list_executions() if r['source_namespace']=='arr-design-executions')
    assert row['source_status']=='failed' and not row['has_preview'] and not row['has_passport']
