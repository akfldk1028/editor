import os
import subprocess
import sys


def test_design_runtime_http_contract(tmp_path):
    script = r'''
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.api.routes_design_runtime import create_design_runtime_router
app = FastAPI()
app.include_router(create_design_runtime_router(public_origin='http://editor.test'))
client = TestClient(app)
base = '/api/v1/design/'
assert client.get(base + 'unknown').status_code == 404
assert client.post(base + 'jobs', json={}, headers={'Origin':'http://evil.test'}).status_code == 403
assert client.post(base + 'jobs', content='{').status_code == 400
assert client.post(base + 'interactive/patch', json=[]).status_code == 400
assert client.post(base + 'interactive/patch', content='{"value":NaN}').status_code == 400
body = {'site_polygon': {'type':'Polygon', 'coordinates':[[[127,37.5],[127.001,37.5],[127.001,37.501],[127,37.501],[127,37.5]]]}, 'options':{'algorithm':'additive'}}
created = client.post(base + 'jobs', json=body)
assert created.status_code == 202, created.text
job_id = created.json()['id']
assert '-' in job_id
assert client.get(base + 'jobs/' + job_id).json()['status'] == 'pending'
assert client.get(base + 'jobs/' + job_id + '/results').json()['total_designs'] == 0
assert client.get(base + 'jobs/00000000-0000-0000-0000-000000000000').status_code == 404
assert client.post(base + 'floor-plan', json={}).status_code in (400, 422)
'''
    result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True,
        env={**os.environ, 'EDITOR_DESIGN_DATA_DIR': str(tmp_path),
             'EDITOR_DESIGN_DATABASE': str(tmp_path / 'execution.sqlite3')}, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr


def test_stream_release_and_database_identity(tmp_path):
    script = r'''
import asyncio
from backend.app.adapters.design_storage import bootstrap
bootstrap.ensure_design_runtime()
from backend.app.api.routes_design_runtime import _stream_response
from django.http import StreamingHttpResponse
from django.conf import settings
closed = []
def chunks():
    try:
        yield b'data: first\n\n'
        yield b'data: second\n\n'
    finally:
        closed.append(True)
async def check():
    stream = _stream_response(StreamingHttpResponse(chunks()))
    assert await anext(stream) == b'data: first\n\n'
    await stream.aclose()
asyncio.run(check())
assert closed == [True]
bootstrap._ready = False
settings.DATABASES['default']['NAME'] = 'different.sqlite3'
try:
    bootstrap.ensure_design_runtime()
except RuntimeError as error:
    assert 'different database' in str(error)
else:
    raise AssertionError('Mismatched database silently accepted')
'''
    result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True,
        env={**os.environ, 'EDITOR_DESIGN_DATA_DIR': str(tmp_path),
             'EDITOR_DESIGN_DATABASE': str(tmp_path / 'execution.sqlite3')}, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
