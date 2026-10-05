"""Real WGS84 mass output must be solved in meters and remain geographically bound."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

WORKER = r'''
import hashlib, json, random
from fastapi import FastAPI
from fastapi.testclient import TestClient
from shapely.geometry import box, mapping
from backend.app.api.routes_design_runtime import create_design_runtime_router
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime
ensure_design_runtime()
from backend.app.modules.design.generation.services.mass_renderer import design_to_geojson
from backend.app.modules.design.generation.services.site_geometry import wgs84_to_utm
app = FastAPI()
app.include_router(create_design_runtime_router())
client = TestClient(app)
site = box(127, 37.5, 127.001, 37.501)
inputs = [[v] for _ in range(5) for v in (0,0,20,18,0)] + [[5],[0],[0.9],[0.7]]
mass = design_to_geojson(inputs, site, wgs84_to_utm(site).area, algorithm='additive')
assert mass is not None
rooms = [{'name':'Living','area':180,'adjacency':['Kitchen']},{'name':'Kitchen','area':90,'adjacency':['Living']}]
options = {'num_generations':1,'population_size':15,'num_variants':2,'num_iterations':20,
           'max_iterations':20,'num_runs':1,'time_limit':0.3,'seed':17}
report = {'mass':mass}
for algorithm in ('ga','subdivision','mcts','packing'):
    random.seed(17)
    body = dict(footprint_geojson=mass['geometry'], coordinate_frame='wgs84', rooms=rooms,
                cell_size=3, algorithm=algorithm, options=options)
    result = client.post('/api/v1/design/floor-plan/',json=body)
    report[algorithm] = {'status':result.status_code,'body':result.json(),
        'request_hash':hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()}
for frame in (None, 'local_meters', 'guessed'):
    body = dict(footprint_geojson=mapping(box(127,37,139,49)),rooms=rooms,cell_size=3,algorithm='subdivision',options=options)
    if frame is not None: body['coordinate_frame'] = frame
    result=client.post('/api/v1/design/floor-plan/',json=body)
    report[str(frame)]={'status':result.status_code,'body':result.json()}
for key, geometry in [('invalid_wgs84', mapping(box(500,37,501,38))), ('projected_budget', mapping(box(127,37,128,38)))]:
    result=client.post('/api/v1/design/floor-plan/',json=dict(footprint_geojson=geometry,coordinate_frame='wgs84',rooms=rooms,algorithm='subdivision'))
    report[key]={'status':result.status_code,'body':result.json()}
print(json.dumps(report))
'''


@pytest.fixture(scope='module')
def report(tmp_path_factory):
    directory = tmp_path_factory.mktemp('floor-coordinate-http')
    env = dict(os.environ, EDITOR_DESIGN_DATA_DIR=str(directory),
               EDITOR_DESIGN_DATABASE=str(directory / 'execution.sqlite3'), PYTHONIOENCODING='utf-8')
    child = subprocess.run([sys.executable, '-c', WORKER], cwd=Path(__file__).resolve().parents[2],
                           env=env, text=True, encoding='utf-8', capture_output=True, timeout=60)
    assert child.returncode == 0, child.stderr
    return json.loads(child.stdout.splitlines()[-1])


@pytest.mark.parametrize('algorithm', ['ga','subdivision','mcts','packing'])
def test_generated_mass_is_solved_in_meters_and_reprojected(report, algorithm):
    from shapely.geometry import shape
    from backend.app.modules.land.projection import wgs84_to_utm
    result = report[algorithm]
    assert result['status'] == 200, result
    body = result['body']
    assert body['grid_info']['active_cells'] > 1
    assert body['coordinate_frame']['input'] == 'wgs84'
    assert body['coordinate_frame']['output'] == 'wgs84'
    assert body['coordinate_frame']['local_unit'] == 'meter'
    assert body['received_request_hash'] == result['request_hash']
    footprint = shape(report['mass']['geometry'])
    features = body['results'][0]['floor_plan']['features']
    local_features = body['results'][0]['floor_plan_local']['features']
    assert features and len(features) == len(local_features)
    for feature, local in zip(features, local_features):
        geographic = shape(feature['geometry'])
        metric = shape(local['geometry'])
        assert footprint.buffer(1e-10).covers(geographic)
        assert metric.bounds[0] >= -1e-7 and metric.bounds[1] >= -1e-7
        assert metric.area > 1
        assert feature['properties']['area_m2'] == pytest.approx(metric.area)
        assert wgs84_to_utm(geographic).area == pytest.approx(metric.area, rel=1e-6)
    assert sum(feature['properties']['area_m2'] for feature in features) <= report['mass']['properties']['footprint_area'] + 0.02


@pytest.mark.parametrize('key', ['None', 'local_meters'])
def test_default_and_explicit_local_coordinates_are_not_guessed_as_wgs84(report, key):
    from shapely.geometry import box, shape
    result = report[key]
    assert result['status'] == 200
    body = result['body']
    assert body['grid_info']['rows'] == 4 and body['grid_info']['cols'] == 4
    assert body['coordinate_frame']['input'] == 'local_meters'
    for result in body['results']:
        for feature in result['floor_plan']['features']:
            assert box(127,37,139,49).buffer(1e-8).covers(shape(feature['geometry']))
        for feature in result['floor_plan_local']['features']:
            assert box(0,0,12,12).buffer(1e-8).covers(shape(feature['geometry']))


@pytest.mark.parametrize('key', ['guessed', 'invalid_wgs84', 'projected_budget'])
def test_bad_coordinate_contract_and_projected_grid_budget_fail_before_generation(report, key):
    assert report[key]['status'] == 400, report[key]
    assert report[key]['body']['error']
    assert report[key]['body']['input_receipt']['scope'] == 'received_body_only'
