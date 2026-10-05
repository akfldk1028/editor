"""Exercise the imported geometry through the real HTTP adapter in isolation."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


WORKER = r'''
import json, random
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.api.routes_design_runtime import create_design_runtime_router

app = FastAPI()
app.include_router(create_design_runtime_router())
client = TestClient(app)
report = {}
footprint = {'type':'Polygon','coordinates':[[[0,0],[12,0],[12,12],[0,12],[0,0]]]}
rooms = [{'name':'Living','area':60,'adjacency':['Kitchen']},{'name':'Kitchen','area':36,'adjacency':['Living']}]
for algorithm in ('ga','subdivision','mcts','packing','graph2plan'):
    random.seed(17)
    response = client.post('/api/v1/design/floor-plan/', json={
        'footprint_geojson':footprint, 'rooms':rooms,'cell_size':3,'algorithm':algorithm,
        'options':{'num_generations':1,'population_size':15,'num_variants':2,
                   'num_iterations':20,'max_iterations':20,'num_runs':1,'time_limit':0.3,'seed':17}})
    report[algorithm] = {'status':response.status_code,'body':response.json()}
site = {'type':'Polygon','coordinates':[[[127,37],[127.001,37],[127.001,37.001],[127,37.001],[127,37]]]}
inputs = [[v] for _ in range(5) for v in (0,0,20,18,0)] + [[5],[0],[0.9],[0.7]]
selected = {'id':0,'inputs':inputs,'algorithm':'additive'}
patch = client.post('/api/v1/design/interactive/patch/',json={
    'message':'북측 상부를 부드럽게 후퇴시켜줘','selected_design':selected})
report['patch'] = {'status':patch.status_code,'body':patch.json()}
preview = client.post('/api/v1/design/interactive/preview/',json={
    'patch_plan':patch.json(),'selected_design':selected,'site_polygon':site,
    'site_area_m2':9800,'constraints':[{'name':'far','type':'Constraint','Requirement':'Less than','val':300,'unit':'%'}],
    'building_type':'공동주택','algorithm':'additive'})
report['preview'] = {'status':preview.status_code,'body':preview.json()}
mass = {'type':'Feature','geometry':site,'properties':{'num_floors':3,'height':9,
    'floor_height':3,'footprint_area':100,'floor_area':300,
    'floor_plates':[{'area':100,'top_height':3*(index+1),'geometry':site} for index in range(3)]}}
operation = client.post('/api/v1/design/interactive/operation/',json={
    'mass_geojson':mass,'site_polygon':site,'operation':{'type':'push_pull_face','delta_floors':-1},'constraints':[]})
report['operation'] = {'status':operation.status_code,'body':operation.json()}
print(json.dumps(report,ensure_ascii=True))
'''


@pytest.fixture(scope="module")
def geometry_report(tmp_path_factory):
    directory = tmp_path_factory.mktemp("design-http-geometry")
    env = dict(os.environ, EDITOR_DESIGN_DATA_DIR=str(directory),
               EDITOR_DESIGN_DATABASE=str(directory / "execution.sqlite3"),
               EDITOR_GRAPH2PLAN_MODEL_DIR=str(directory / "missing-graph2plan"),
               PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    child = subprocess.run([sys.executable, "-c", WORKER], cwd=Path(__file__).resolve().parents[2],
                           env=env, text=True, encoding="utf-8", capture_output=True, timeout=60)
    assert child.returncode == 0, child.stderr
    return json.loads(child.stdout.splitlines()[-1])


@pytest.mark.parametrize("algorithm", ["ga", "subdivision", "mcts", "packing"])
def test_original_floor_algorithms_return_real_geometry(geometry_report, algorithm):
    response = geometry_report[algorithm]
    assert response["status"] == 200, response
    body = response["body"]
    assert body["algorithm"] == algorithm
    assert body["num_results"] > 0
    from shapely.geometry import box, shape
    footprint = box(0, 0, 12, 12)
    features = body["results"][0]["floor_plan"]["features"]
    assert features
    for feature in features:
        polygon = shape(feature["geometry"])
        assert polygon.is_valid and polygon.area > 0
        assert footprint.buffer(1e-8).covers(polygon)
    assert body["design_acceptance"]["status"] == "not_verified"
    assert body["input_receipt"]["scope"] == "received_body_only"


def test_graph2plan_reports_missing_optional_model_explicitly(geometry_report):
    response = geometry_report["graph2plan"]
    assert response["status"] == 200, response
    assert response["body"]["num_results"] == 0
    assert response["body"]["error"]
    assert "not" in response["body"]["error"].lower()


def test_interactive_preview_keeps_original_payload_contract(geometry_report):
    assert geometry_report["patch"]["status"] == 200
    response = geometry_report["preview"]
    assert response["status"] == 200, response
    assert response["body"]["mode"] == "preview"
    assert response["body"]["selected_design_id"] == 0
    assert response["body"]["candidates"][0]["mass_geojson"]["type"] == "Feature"


def test_interactive_operation_trims_actual_floor_stack(geometry_report):
    response = geometry_report["operation"]
    assert response["status"] == 200, response
    result = response["body"]
    assert result["mode"] == "interactive_operation"
    properties = result["feature"]["properties"]
    assert properties["num_floors"] == 2
    assert properties["height"] == 6
    assert properties["floor_area"] == 200
    assert len(properties["floor_plates"]) == 2
    assert properties["operation_history"][-1]["delta_floors"] == -1
    assert result["agent_reviews"]


def test_graph2plan_installed_model_produces_geometry_through_http(tmp_path):
    from backend.app.modules.design.generation.services.graph2plan_runtime import model_directory
    directory = model_directory()
    if not (directory / "model/model.pth").is_file():
        pytest.skip("Install the local Graph2Plan reference model to run inference verification")
    worker = r'''
import json, sys
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.api.routes_design_runtime import create_design_runtime_router
original_path = list(sys.path)
app = FastAPI()
app.include_router(create_design_runtime_router())
client = TestClient(app)
results = []
for rooms in ([{'name':'Living','area':100}], [
    {'name':'Living','area':60,'adjacency':['Kitchen']},
    {'name':'Kitchen','area':36,'adjacency':['Living']} ]):
    response = client.post('/api/v1/design/floor-plan/',json={
        'footprint_geojson':{'type':'Polygon','coordinates':[[[0,0],[12,0],[12,12],[0,12],[0,0]]]},
        'rooms':rooms,'algorithm':'graph2plan','options':{'num_variants':1}})
    results.append({'status':response.status_code,'body':response.json()})
assert sys.path == original_path
assert 'model' not in sys.modules and 'model.model' not in sys.modules
print(json.dumps(results))
'''
    env = dict(os.environ, EDITOR_DESIGN_DATA_DIR=str(tmp_path),
               EDITOR_DESIGN_DATABASE=str(tmp_path / "execution.sqlite3"),
               EDITOR_GRAPH2PLAN_MODEL_DIR=str(directory),
               PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    child = subprocess.run([sys.executable, "-c", worker], cwd=Path(__file__).resolve().parents[2],
                           env=env, text=True, encoding="utf-8", capture_output=True, timeout=60)
    assert child.returncode == 0, child.stderr
    from shapely.geometry import box, shape
    for index, response in enumerate(json.loads(child.stdout.splitlines()[-1])):
        assert response["status"] == 200, response
        body = response["body"]
        assert "error" not in body, body
        assert body["num_results"] == 1
        features = body["results"][0]["floor_plan"]["features"]
        assert len(features) == index + 1
        for feature in features:
            geometry = shape(feature["geometry"])
            assert geometry.is_valid and geometry.area > 0
            assert box(0, 0, 12, 12).covers(geometry)
        assert body["design_acceptance"]["status"] == "not_verified"
