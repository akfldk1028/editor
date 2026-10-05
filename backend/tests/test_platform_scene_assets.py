import hashlib

from fastapi.testclient import TestClient
from backend.app.main import create_app


def test_bound_scene_asset_is_hash_addressed_and_tampering_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv('EDITOR_PLATFORM_DATA_DIR', str(tmp_path))
    content = b'glTF\x02\x00\x00\x00retained-model-fixture'
    digest = hashlib.sha256(content).hexdigest()
    directory = tmp_path / 'scene-assets'
    directory.mkdir()
    artifact = directory / (digest + '.glb')
    artifact.write_bytes(content)
    api = TestClient(create_app())
    path = '/api/v1/platform/scene-assets/' + digest + '.glb'
    response = api.get(path)
    assert response.status_code == 200
    assert response.content == content
    assert response.headers['content-type'] == 'model/gltf-binary'
    artifact.write_bytes(b'changed')
    assert api.get(path).status_code == 409
    assert api.get('/api/v1/platform/scene-assets/' + '0' * 64 + '.glb').status_code == 404
    assert api.get('/api/v1/platform/scene-assets/not-a-hash.glb').status_code == 404
