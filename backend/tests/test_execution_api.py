from io import BytesIO
import hashlib
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from backend.app.modules.platform.projects import ProjectService
from backend.app.modules.platform.repository import ProjectRepository
from backend.app.schemas.platform import ProjectCreate


class Sources:
    version=2
    owner='local'
    unavailable=False

    async def list_projects(self):
        return [{'owner_project_id':'owner','branch_id':'main'}]

    async def get_scene(self,identifier):
        if self.unavailable:
            from backend.app.adapters.orchestrator import OwnerUnavailable
            raise OwnerUnavailable('fixture unavailable')
        return {'id':identifier,'projectId':'scene-project','version':self.version,'ownerId':self.owner}


@pytest.fixture
def execution_api(tmp_path):
    from backend.app.modules.platform.routers.platform import create_platform_router
    from backend.app.modules.design.execution_catalog import ExecutionCatalog
    from backend.app.modules.design.artifacts import ArtifactArchive,import_artifacts
    sources=Sources();projects=ProjectRepository(tmp_path/'projects')
    body=ProjectCreate(owner_project_id='owner',branch_id='main',scene_id='scene',scene_project_id='scene-project',scene_revision=2)
    project=projects.create('local',body)
    other=projects.create('other',body)
    source=tmp_path/'source';run=source/'single-executions'/'run-1';run.mkdir(parents=True)
    original=json.dumps({'execution_id':'run-1','status':'running','private_source_path':'D:/original/private'}).encode()
    (run/'execution.json').write_bytes(original)
    image=BytesIO();Image.new('RGB',(1,1),'white').save(image,format='PNG');png=image.getvalue()
    (run/'mass.png').write_bytes(png)
    (run/'mass.png.passport.json').write_text('{"evidence":"original"}',encoding='utf8')
    root=tmp_path/'design';archive=ArtifactArchive(root/'artifacts')
    import_artifacts(archive,source,'arr-maas-cache',dry_run=False)
    catalog=ExecutionCatalog(root);catalog.register('arr-maas-cache')
    source.rename(tmp_path/'source-offline')
    service=ProjectService(projects,sources,sources)
    app=FastAPI();app.include_router(create_platform_router(project_service=service,
        public_origin='http://127.0.0.1:5186',execution_catalog=catalog))
    client=TestClient(app)
    url=f'/api/v1/platform/projects/{project.project_id}/design'
    return client,url,sources,catalog,archive,other.project_id,png,original


def catalog_id(client,url):
    response=client.get(url+'/archive/executions')
    assert response.status_code==200
    return response.json()['items'][0]['catalog_id']


def test_archive_requires_local_project_and_valid_pagination(execution_api):
    client,url,_,_,_,other,_,_=execution_api
    assert client.get(url+'/archive/executions').status_code==200
    assert client.get(url+'/archive/executions?limit=101').status_code==422
    assert client.get(url+'/archive/executions?offset=-1').status_code==422
    assert client.get('/api/v1/platform/projects/missing/design/archive/executions').status_code==404
    assert client.get(f'/api/v1/platform/projects/{other}/design/archive/executions').status_code==404
    assert client.get(url+'/executions').json()['items']==[]
    assert client.get(url+'/executions/not-a-catalog-id').status_code==422
    assert client.get(url+'/executions/'+ 'a'*64 +'/artifacts/%2e%2e%5cprivate/download').status_code==422


def test_attachment_checks_origin_live_scene_and_strict_body(execution_api):
    client,url,sources,_,_,_,_,_=execution_api
    identifier=catalog_id(client,url);body={'catalog_id':identifier,'scene_revision':2}
    assert client.post(url+'/executions',json=body,headers={'origin':'https://other.invalid'}).status_code==403
    assert client.post(url+'/executions',json=body,headers={'sec-fetch-site':'cross-site'}).status_code==403
    for invalid in [dict(body,scene_revision=True),dict(body,catalog_id='../private'),dict(body,raw_path='private')]:
        assert client.post(url+'/executions',json=invalid).status_code==422
    sources.version=3
    assert client.post(url+'/executions',json=body).status_code==409
    sources.version=2;sources.owner='other'
    assert client.post(url+'/executions',json=body).status_code==409
    assert client.get(url+'/executions').json()['items']==[]
    sources.owner='local'
    sources.unavailable=True
    assert client.post(url+'/executions',json=body).status_code==503
    sources.unavailable=False
    assert client.post(url+'/executions',json=dict(body,catalog_id='f'*64)).status_code==404
    response=client.post(url+'/executions',json=body)
    assert response.status_code==201
    assert response.json()['catalog_id']==identifier
    assert client.get(url+'/executions').json()['items'][0]['catalog_id']==identifier


def test_details_and_artifacts_require_attachment_and_preserve_bytes(execution_api):
    client,url,_,catalog,archive,other,png,original=execution_api
    identifier=catalog_id(client,url);detail=url+'/executions/'+identifier
    assert client.get(detail).status_code==404
    assert client.get(detail+'/artifacts/'+'a'*64).status_code==404
    assert client.post(url+'/executions',json={'catalog_id':identifier,'scene_revision':2}).status_code==201
    def stored_bytes():
        paths=[catalog.path,*archive.directory.rglob('*')]
        return {str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in paths if path.is_file()}
    before=stored_bytes()
    response=client.get(detail);assert response.status_code==200
    page=response.json();assert page['execution']['catalog_id']==identifier
    assert len(page['items'])==3
    assert 'D:/original/private' not in json.dumps(page)
    assert client.get(detail+'?limit=101').status_code==422
    for item in page['items']:
        artifact=detail+'/artifacts/'+item['artifact_id']
        assert client.get(f'/api/v1/platform/projects/{other}/design/executions/{identifier}/artifacts/{item["artifact_id"]}/download').status_code==404
        download=client.get(artifact+'/download')
        assert download.status_code==200
        assert download.headers['x-content-type-options']=='nosniff'
        assert 'private' in download.headers['cache-control'] and 'immutable' in download.headers['cache-control']
        assert download.headers.get('etag')
        assert 'attachment' in download.headers['content-disposition']
        if download.content==png:
            inline=client.get(artifact)
            assert inline.status_code==200 and inline.content==png
            assert inline.headers['content-type'].startswith('image/png')
            assert inline.headers['x-content-type-options']=='nosniff'
        else:
            assert download.headers['content-type'].startswith('application/json')
            if download.content==original:
                assert json.loads(download.content)['private_source_path']=='D:/original/private'
            inline=client.get(artifact)
            assert inline.status_code==404
    assert client.get(detail+'/artifacts/'+'f'*64+'/download').status_code==404
    assert client.get(url+'/archive/executions').status_code==200
    assert client.get(url+'/executions').status_code==200
    assert client.get(detail).status_code==200
    assert stored_bytes()==before


def test_corrupt_archived_blob_returns_service_error(execution_api):
    client,url,_,_,archive,_,_,_=execution_api
    identifier=catalog_id(client,url)
    assert client.post(url+'/executions',json={'catalog_id':identifier,'scene_revision':2}).status_code==201
    detail=url+'/executions/'+identifier
    items=client.get(detail).json()['items']
    for entry in archive.entries('arr-maas-cache').values():
        archive._blob(entry).write_bytes(b'corrupt')
    for item in items:
        assert client.get(detail+'/artifacts/'+item['artifact_id']+'/download').status_code==503


def test_corrupt_catalog_metadata_is_storage_failure_not_binding_conflict(execution_api):
    import sqlite3
    client,url,_,catalog,_,_,_,_=execution_api
    with sqlite3.connect(catalog.path) as db:
        db.execute("UPDATE executions SET summary_json='not json'")
    assert client.get(url+'/archive/executions').status_code==503
