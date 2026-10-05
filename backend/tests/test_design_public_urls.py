import json
import os
from pathlib import Path
import subprocess
import sys


def test_normalizes_only_local_url_fields_without_mutating_evidence():
    from backend.app.modules.design.public_urls import normalize_design_urls
    source = {'preview_url': '/design/maas/one', 'url': 'https://example.org/design/one',
              'geometry_hash': '/design/unchanged', 'request': '/design/unchanged',
              'nested': [{'href': '/design/maas/two', 'source_url': '//example.org/design/three'}]}
    before = json.dumps(source)
    result = normalize_design_urls(source)
    assert result['preview_url'] == '/api/v1/design/maas/one'
    assert result['nested'][0]['href'] == '/api/v1/design/maas/two'
    assert result['url'] == source['url']
    assert result['nested'][0]['source_url'] == source['nested'][0]['source_url']
    assert result['geometry_hash'] == source['geometry_hash']
    assert result['request'] == source['request']
    assert json.dumps(source) == before


def test_real_single_execution_assets_through_next_bff(tmp_path):
    script = r'''
import hashlib, json, os, shutil, socket, subprocess, threading, time
from pathlib import Path
import uvicorn
from fastapi import FastAPI
from backend.app.api.routes_design_runtime import create_design_runtime_router
from backend.app.api.routes_design_workspace import create_design_workspace_router
from backend.app.modules.design.generation.maas.geometry_language import architectural_shape_programs
app = FastAPI()
app.include_router(create_design_workspace_router())
app.include_router(create_design_runtime_router())
sock = socket.socket()
sock.bind(('127.0.0.1', 0))
port = sock.getsockname()[1]
server = uvicorn.Server(uvicorn.Config(app, log_level='error'))
thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
thread.start()
for _ in range(100):
    if server.started: break
    time.sleep(.05)
assert server.started
code = r"""
import { GET, POST } from './app/api/v1/design/[...path]/route.ts';
async function call(url, body) {
  const target = new URL(url, 'http://editor.test');
  const path = target.pathname.replace(/^\/api\/v1\/design\//, '').replace(/\/$/, '').split('/');
  const request = new Request(target, body ? {method:'POST', body:JSON.stringify(body)} : {});
  return (body ? POST : GET)(request, {params:Promise.resolve({path})});
}
const created = await call('/api/v1/design/maas/single-executions', {program:JSON.parse(process.env.TEST_PROGRAM)});
const data = await created.json();
if (created.status !== 201) throw Error(JSON.stringify(data));
for (const key of ['preview_url', 'passport_url', 'manifest_url']) {
  if (!data[key].startsWith('/api/v1/design/')) throw Error(key + ':' + data[key]);
}
const preview = await call(data.preview_url);
const bytes = new Uint8Array(await preview.arrayBuffer());
if (preview.status !== 200 || bytes[0] !== 137 || bytes[1] !== 80) throw Error('actual PNG unavailable');
const passportResponse = await call(data.passport_url);
const passport = await passportResponse.json();
if (passportResponse.status !== 200 || passport.geometry_hash !== data.geometry_hash) throw Error('passport identity mismatch');
const executionManifest = await call(data.manifest_url);
if(executionManifest.status !== 200 || (await executionManifest.json()).geometry_hash !== data.geometry_hash) throw Error('manifest identity mismatch');
const urls = [];
function collect(v) { if (Array.isArray(v)) v.forEach(collect); else if(v && typeof v === 'object') for(const [k,x] of Object.entries(v)) {if(typeof x === 'string' && (k === 'url' || k === 'href' || k.endsWith('_url')) && x.includes('/elevation/')) urls.push(x); else collect(x);} }
collect(passport);
if (!urls.length) {
  if(passport.elevation_evidence?.status !== 'failed' || !passport.elevation_evidence.error.includes('final geometry identity mismatch')) throw Error('unexplained missing elevation');
  const unavailable = await call(data.preview_url.replace('/preview/', '/elevation/front/'));
  if(unavailable.status !== 404) throw Error('uncertified elevation must remain unavailable');
}
for(const url of urls) { if(!url.startsWith('/api/v1/design/')) throw Error(url); const response=await call(url); if(response.status !== 200) throw Error(url + ':' + response.status); }
const archive = await call('/api/v1/design/maas/executed-masses?run_id=' + encodeURIComponent(data.archive_run_id));
const manifest = await archive.json();
if(archive.status !== 200 || manifest.selected_run_id !== data.archive_run_id || !manifest.runs.some(x=>x.run_id === data.archive_run_id)) throw Error('archive visibility');
console.log(JSON.stringify({execution_id:data.execution_id, geometry_hash:data.geometry_hash, elevations:urls.length}));
"""
try:
    windows_bun = Path(os.environ.get('APPDATA', '')) / 'npm/node_modules/bun/bin/bun.exe'
    bun = str(windows_bun) if windows_bun.is_file() else shutil.which('bun')
    result = subprocess.run([bun, '--eval', code], cwd='frontend/app/editor', capture_output=True, text=True,
        env={**os.environ, 'EDITOR_BACKEND_URL':f'http://127.0.0.1:{port}', 'TEST_PROGRAM':json.dumps(architectural_shape_programs()[0].to_dict())}, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    identity = json.loads(result.stdout)
    directory = Path(os.environ['EDITOR_DESIGN_DATA_DIR']) / 'single-executions' / identity['execution_id']
    files = {path:hashlib.sha256(path.read_bytes()).hexdigest() for path in directory.rglob('*') if path.is_file()}
    raw = json.loads((directory / 'mass.png.passport.json').read_text(encoding='utf-8'))
    assert raw['geometry_hash'] == identity['geometry_hash']
    from backend.app.modules.design.execution_archive import ExecutionArchive
    public = ExecutionArchive(os.environ['EDITOR_DESIGN_DATA_DIR']).passport('single-execution:' + identity['execution_id'], 1)
    assert public['geometry_hash'] == raw['geometry_hash']
    assert all(hashlib.sha256(path.read_bytes()).hexdigest() == digest for path,digest in files.items())
    from backend.app.modules.design.artifacts import ArtifactArchive, import_artifacts
    source = directory.parent.parent / 'import-source'
    captured = source / 'executed-masses' / 'captured-real-run'
    captured.mkdir(parents=True)
    filename = 'mass-01-' + identity['geometry_hash'][:8] + '.png'
    shutil.copyfile(directory / 'mass.png', captured / filename)
    shutil.copyfile(directory / 'mass.png.passport.json', captured / (filename + '.passport.json'))
    archive = ArtifactArchive(directory.parent.parent / 'artifacts')
    import_artifacts(archive, source, 'arr-maas-cache', dry_run=False)
    assert ExecutionArchive(directory.parent.parent).passport('captured-real-run', 1) == raw
    stored = archive.file('arr-maas-cache', 'executed-masses/captured-real-run/' + filename + '.passport.json')
    assert stored.read_bytes() == (directory / 'mass.png.passport.json').read_bytes()
finally:
    server.should_exit = True
    thread.join(10)
'''
    result = subprocess.run([sys.executable, '-c', script], cwd=Path(__file__).resolve().parents[2],
        env={**os.environ, 'EDITOR_DESIGN_DATA_DIR': str(tmp_path), 'EDITOR_DESIGN_DATABASE': str(tmp_path / 'jobs.sqlite3')},
        capture_output=True, text=True, timeout=110)
    assert result.returncode == 0, result.stdout + result.stderr
