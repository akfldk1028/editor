"""A Mass cycle sent as content from another server exports like a local one.

Agents share no disk: the bundle carries the cycle's files, the Mass-host paths pinned in
state.json are remapped onto a private staging copy, and every result file is served back
by an API-relative href whose bytes match the artifact sha256.
"""
import hashlib
import io
import json
from pathlib import Path
import shutil
from unittest.mock import patch
import zipfile

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.app.api.routes_design_runtime import create_design_runtime_router
from backend.app.modules.design.generation.maas import delivered_mass_bundle as bundle
from backend.app.modules.design.generation.maas import delivered_mass_export as export

BASE = '/api/v1/design/maas/delivered-mass-export'
NAME = 'book:selected'
CERTIFICATE = {'name': NAME, 'shape_id': 'delivered', 'certificate_id': 'cert'}
MESH = {'vertices': [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 3]],
        'triangles': [[0, 2, 1], [0, 1, 3], [1, 2, 3], [2, 0, 3]]}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


def package(candidate, staging, request):
    target = staging / 'dataset/candidates' / candidate['candidate_id']
    target.mkdir(parents=True)
    write(target / 'mesh.json', candidate['mesh'])
    write(target / 'mass' / 'program.json', candidate['geometry_program'])
    export.write_glb(candidate['mesh'], target / 'selected.glb')
    return target


@pytest.fixture
def cycle(tmp_path, monkeypatch):
    """The Mass host's completed cycle; its BOOK source lives outside the workspace."""
    host = tmp_path / 'mass-host'
    ws, book = host / 'ws', host / 'library' / 'book-r1'
    record = book / 'records.json'
    write(record, {'trace': 'selected'})
    registry = ws / 'runs/books/r1.json'
    entry = {'delivered_shape_id': 'delivered', 'numeric_certificate': CERTIFICATE,
             'program': {'source': 'authored'}, 'original_storey_evidence': {
                 'floor_elevations_m': [0, 3], 'floor_center_elevations_m': [1.5]},
             'delivered_floor_evidence': {'delivered_floor_center_elevations_m': [1.5]}}
    write(registry, {'book_dir': str(book), 'entries': {NAME: entry}})
    complete = ws / 'runs/cycle-r1/complete.json'
    write(complete, {'status': 'complete', 'round': 'r1', 'feedback': {'champion': NAME}})
    write(complete.with_name('state.json'), {
        'status': 'complete', 'config': {'round': 'r1', 'pnu': 'parcel', 'building_type': 'office'},
        'actions': {'import': {'outputs': {str(registry): export.file_hash(registry),
                                           str(record): export.file_hash(record)}},
                    'complete': {'outputs': {str(complete): export.file_hash(complete)}}}})
    request = {'completion_sha256': export.file_hash(complete), 'source_run_id': 'run-1',
               'source_identity': {'project': 'p', 'branch': 'b', 'pnu': 'parcel', 'building_type': 'office'},
               'source_versions': {'geometry.mass': 1}}
    monkeypatch.setenv('EDITOR_DESIGN_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setenv('EDITOR_DELIVERED_MASS_EXPORT_ROOT', str(tmp_path / 'exports'))
    monkeypatch.setenv('EDITOR_MASS_SOURCE_ROOTS', json.dumps([str(host)]))
    monkeypatch.delenv('A2A_TOKEN', raising=False)
    return {'host': host, 'ws': ws, 'book': book, 'complete': complete, 'request': request,
            'exports': tmp_path / 'exports'}


def zipped(members):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name, data in members.items():
            info = zipfile.ZipInfo(name)
            info.filename = name  # keep a raw backslash; ZipInfo rewrites it on Windows
            archive.writestr(info, data)
    return buffer.getvalue()


def make_bundle(cycle, *, request=None, workspace_origin=None):
    """What MassAgent sends: request.json, workspace/<relative>, sources/<i>/<relative>."""
    ws, book = cycle['ws'], cycle['book']
    members = {f'workspace/{p.relative_to(ws).as_posix()}': p.read_bytes() for p in ws.rglob('*') if p.is_file()}
    members.update({f'sources/0/{p.relative_to(book).as_posix()}': p.read_bytes() for p in book.rglob('*') if p.is_file()})
    members['request.json'] = json.dumps({
        'request': request or cycle['request'], 'round': 'r1',
        # Separators and (Windows) case differ from state.json on purpose.
        'origins': {'workspace': workspace_origin or (ws.as_posix().upper() if ws.drive else ws.as_posix()),
                    'sources': {book.as_posix(): 'sources/0'}}}).encode()
    return zipped(members)


def client():
    app = FastAPI()
    app.include_router(create_design_runtime_router(public_origin='http://editor.test'))
    return TestClient(app)


def exporting():
    return (patch.object(export, 'reconstruct', return_value=(MESH, CERTIFICATE)),
            patch.object(export, 'build_package', side_effect=package))


def test_remap_moves_mass_host_paths_onto_staging_copies():
    origins = {'C:\\Mass\\WS': '/stage/workspace', 'C:/Mass/WS/books/b1': '/stage/sources/0',
               '/home/mass/ws': '/stage/posix'}
    assert export.remap_origin('c:\\mass\\ws\\runs\\cycle-1\\complete.json', origins) == '/stage/workspace/runs/cycle-1/complete.json'
    # The longest prefix wins when a source sits inside the workspace.
    assert export.remap_origin('C:\\Mass\\WS\\books\\b1\\r.json', origins) == '/stage/sources/0/r.json'
    assert export.remap_origin('C:/Mass/WS', origins) == '/stage/workspace'
    # Component boundaries and POSIX case are respected; unmatched paths are returned unchanged.
    assert export.remap_origin('C:/Mass/WS2/x.json', origins) == 'C:/Mass/WS2/x.json'
    assert export.remap_origin('/home/Mass/ws/x.json', origins) == '/home/Mass/ws/x.json'
    assert export.remap_origin('/home/mass/ws/x.json', origins) == '/stage/posix/x.json'


@pytest.mark.parametrize('name', ['../escape.json', '/abs.json', 'C:/abs.json', 'c:rel.json', 'workspace\\x.json',
                                  'workspace/../../x.json', 'workspace/./x.json', 'workspace/a:stream',
                                  'workspace/nul.json', 'other/x.json', 'sources/x/y.json', 'workspace/'])
def test_unsafe_members_are_refused_before_anything_escapes(tmp_path, name):
    staging = tmp_path / 'stage' / 'inner'
    staging.mkdir(parents=True)
    with pytest.raises(bundle.BundleRefused):
        bundle.extract(zipped({'request.json': b'{}', name: b'x'}), staging)
    assert not (tmp_path / 'escape.json').exists() and not (tmp_path / 'stage' / 'x.json').exists()


def test_bundle_must_be_a_zip_and_request_must_be_canonical(cycle):
    with pytest.raises(bundle.BundleRefused, match='zip'):
        bundle.export_bundle(b'not a zip')
    with_path = {**cycle['request'], 'completion_path': str(cycle['complete'])}
    with pytest.raises(bundle.BundleRefused, match='canonical'):
        bundle.export_bundle(make_bundle(cycle, request=with_path))
    with pytest.raises(bundle.BundleRefused, match='origins'):
        bundle.export_bundle(make_bundle(cycle, workspace_origin='relative/ws'))
    assert not any((cycle['exports'] / '.incoming').iterdir())


def test_bundle_exports_without_the_mass_disk_and_serves_every_href(cycle):
    body = make_bundle(cycle)
    shutil.rmtree(cycle['host'])  # nothing may be read from the Mass host's disk
    api = client()
    reconstruct, build = exporting()
    with reconstruct as rebuilt, build:
        response = api.post(BASE + '/bundle/', content=body, headers={'Content-Type': 'application/zip'})
        assert response.status_code == 200, response.text
        result = response.json()
        assert result['status'] == 'succeeded', result
        # A resend stages a fresh folder yet matches the receipt (evidence is recorded by Mass-host path).
        assert api.post(BASE + '/bundle/', content=body).json() == result
        assert rebuilt.call_count == 1
    request_hash = export.digest(cycle['request'])
    assert result['request_hash'] == request_hash
    assert not any((cycle['exports'] / '.incoming').iterdir())
    receipt = json.loads((cycle['exports'] / request_hash / 'receipt.json').read_text(encoding='utf-8'))
    assert all('.incoming' not in path for path in receipt['evidence'])
    assert 'href' not in json.dumps(receipt)  # receipt bytes keep their pre-href shape

    for artifact in result['artifacts']:
        assert artifact['href'].startswith(f'design/maas/delivered-mass-export/{request_hash}/files/')
        served = api.get('/api/v1/' + artifact['href'])
        assert served.status_code == 200
        assert hashlib.sha256(served.content).hexdigest() == artifact['sha256'] == export.file_hash(artifact['path'])
    handoff = result['elevation_handoff']['request']
    glb = api.get('/api/v1/' + handoff['selected_glb_href']).content
    assert hashlib.sha256(glb).hexdigest() == handoff['source_sha256']
    assert any(a['href'] == handoff['selected_glb_href'] for a in result['artifacts'])
    assert handoff['package_href'] == (f'design/maas/delivered-mass-export/{request_hash}'
                                       f"/package.zip?candidate={handoff['candidate']}")
    archive = zipfile.ZipFile(io.BytesIO(api.get('/api/v1/' + handoff['package_href']).content))
    prefix = f"candidates/{handoff['candidate']}/"
    assert sorted(archive.namelist()) == sorted(prefix + n for n in ('mass/program.json', 'mesh.json', 'selected.glb'))
    assert archive.read(prefix + 'selected.glb') == glb


def test_path_export_is_unchanged_but_gains_hrefs(cycle):
    request = {**cycle['request'], 'completion_path': str(cycle['complete'])}
    reconstruct, build = exporting()
    with reconstruct, build:
        result = export.export_delivered_mass(request, roots=[cycle['ws']])
        assert result['status'] == 'succeeded', result
        assert export.export_delivered_mass(request, roots=[cycle['ws']]) == result
    assert result['request_hash'] == export.digest(request)
    target = cycle['exports'] / result['request_hash']
    for artifact in result['artifacts']:
        relative = Path(artifact['path']).relative_to(target).as_posix()
        assert artifact['href'] == f"design/maas/delivered-mass-export/{result['request_hash']}/files/{relative}"
    receipt = json.loads((target / 'receipt.json').read_text(encoding='utf-8'))
    assert str(cycle['complete'].resolve()) in receipt['evidence']


def test_files_and_package_are_confined_to_their_export(cycle, tmp_path):
    from django.http import Http404
    from django.test import RequestFactory
    from backend.app.api.design_runtime.delivered_mass_views import delivered_mass_file, delivered_mass_package
    request_hash = 'a' * 64
    target = cycle['exports'] / request_hash
    (target / 'dataset/candidates/c1').mkdir(parents=True)
    (target / 'dataset/candidates/c1/selected.glb').write_bytes(b'glTF exact')
    (cycle['exports'] / 'secret.txt').write_bytes(b'secret')
    (target / 'dataset' / 'outside.txt').write_bytes(b'outside')
    api = client()
    served = api.get(f'{BASE}/{request_hash}/files/dataset/candidates/c1/selected.glb')
    assert served.status_code == 200 and served.content == b'glTF exact'
    for path in (f'{BASE}/{request_hash}/files/missing.glb', f'{BASE}/{"A" * 64}/files/x', f'{BASE}/.incoming/files/x',
                 f'{BASE}/{request_hash}/package.zip?candidate=missing', f'{BASE}/{request_hash}/package.zip?candidate=..',
                 f'{BASE}/{request_hash}/package.zip'):
        assert api.get(path).status_code == 404, path
    factory = RequestFactory()
    for member in ('../secret.txt', '../' + request_hash + '/../secret.txt', str(cycle['exports'] / 'secret.txt')):
        with pytest.raises(Http404):
            delivered_mass_file(factory.get('/'), request_hash, member)
    with pytest.raises(Http404):
        delivered_mass_package(factory.get('/', {'candidate': '../dataset'}), request_hash)


def test_agent_token_guards_the_three_new_doors(cycle, monkeypatch):
    monkeypatch.setenv('A2A_TOKEN', 'mesh-secret')
    api = client()
    request_hash = 'b' * 64
    doors = [('post', BASE + '/bundle/'), ('get', f'{BASE}/{request_hash}/files/receipt.json'),
             ('get', f'{BASE}/{request_hash}/package.zip?candidate=c1')]
    for method, path in doors:
        assert getattr(api, method)(path).status_code == 401, path
        assert getattr(api, method)(path, headers={'Authorization': 'Bearer wrong'}).status_code == 401, path
    good = {'Authorization': 'Bearer mesh-secret'}
    assert api.post(BASE + '/bundle/', content=b'not a zip', headers=good).status_code == 400
    assert api.get(f'{BASE}/{request_hash}/files/receipt.json', headers=good).status_code == 404
    # The same-host probe keeps its existing contract.
    assert api.get(BASE + '/').status_code == 200
