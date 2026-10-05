import ast
import copy
import json
from pathlib import Path
import types

import pytest
from shapely.geometry import Polygon, box, mapping, shape

from backend.app.modules.land.projection import utm_to_wgs84, wgs84_to_utm
from backend.app.modules.design.job_spec import prepare_job
from backend.app.modules.design.optimization.evaluator import evaluate_candidate

CAPTURED = json.loads((Path(__file__).parent/'fixtures/additive_geometry_source.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('case', CAPTURED['cases'])
def test_captured_original_geometry_parity_without_source_checkout(case):
    actual = evaluate_candidate(case['inputs'], case['prepared'], envelope=case['envelope'])
    assert actual['rejections'] == []
    assert actual['outputs'] == pytest.approx(case['outputs'], abs=1e-8)
    assert actual['geometry']['properties'] == case['geometry']['properties']
    assert shape(actual['geometry']['geometry']).symmetric_difference(shape(case['geometry']['geometry'])).area < 1e-14


def prepared(site=None, constraints=None):
    site = site if site is not None else box(320000, 4150000, 320080, 4150080)
    geometry = json.loads(json.dumps(mapping(utm_to_wgs84(site))))
    return prepare_job({'site_polygon': geometry, 'constraints': constraints or [],
                        'job_spec': {'options': {'building_type': '업무시설', 'algorithm': 'additive'}}})


def genes(*, width=20, depth=20, floors=4, upper=0.8, step=0.5, x=0):
    return [[value] for _ in range(5) for value in (x, 0, width, depth, 0)] + [[floors], [0], [upper], [step]]


def test_valid_candidate_has_shared_metrics_geometry_and_search_provenance():
    spec = prepared()
    original = copy.deepcopy(spec)
    result = evaluate_candidate(genes(), spec)
    assert result['rejections'] == []
    assert result['geometry']['properties']['floor_area'] == result['metrics']['floor_area']
    assert result['geometry']['properties']['far'] == result['metrics']['far']
    assert len(result['outputs']) == len(spec['job_spec']['outputs'])
    assert result['repair']['provenance'] == 'search_defaults'
    assert result['geometry']['properties']['num_floors'] == 4
    assert spec == original
    json.dumps(result, allow_nan=False)
    from backend.app.modules.design.native_repository import canonical_json
    canonical_json(result)


@pytest.mark.parametrize('values', [genes(x=1000), [], [[float('nan')]] * 29, [[True]] * 29])
def test_invalid_geometry_or_genome_never_has_success_outputs(values):
    result = evaluate_candidate(values, prepared())
    assert result['geometry'] is None and result['outputs'] == []
    assert result['rejections']
    json.dumps(result, allow_nan=False)


def test_empty_setback_and_empty_sunlight_clip_reject_instead_of_fallback():
    spec = prepared()
    assert evaluate_candidate(genes(), spec, limits={'road_setback_m': 100})['rejections']
    envelope = {'slanted_polygons': [{'corners': [[127, 37, 12], [127.001, 37, 12], [127.001, 37.001, 12], [127, 37.001, 12]]}]}
    assert evaluate_candidate(genes(), spec, envelope=envelope)['rejections']


def test_one_floor_never_emits_phantom_upper_plate():
    result = evaluate_candidate(genes(floors=1), prepared())
    assert not result['rejections']
    props = result['geometry']['properties']
    assert 'upper_geometry' not in props and 'step_floor' not in props
    assert result['metrics']['stepback_factor'] == 0


def test_holes_and_concave_geometry_preserved_when_no_upper_plate():
    site = Polygon([(320000,4150000),(320080,4150000),(320080,4150080),(320040,4150080),(320040,4150040),(320000,4150040)],
                   holes=[[(320050,4150010),(320060,4150010),(320060,4150020),(320050,4150020)]])
    result = evaluate_candidate(genes(width=100, depth=100, floors=1, upper=1), prepared(site),
                                limits={'bcr_limit_pct':100,'adjacent_setback_m':0,'road_setback_m':0,'north_setback_m':0})
    assert result['rejections'] == []
    geometry = wgs84_to_utm(shape(result['geometry']['geometry']))
    assert len(geometry.interiors) == 1
    assert geometry.symmetric_difference(site).area < 0.001


@pytest.mark.parametrize('constraint', [
    {'name':'height','type':'Constraint','Requirement':'Greater than','val':10},
    {'name':'bcr','type':'Constraint','Requirement':'Less than','val':-1},
])
def test_unsupported_repair_limit_semantics_are_explicit(constraint):
    assert evaluate_candidate(genes(), prepared(constraints=[constraint]))['rejections']


def test_unsatisfied_one_floor_height_is_rejected():
    assert evaluate_candidate(genes(), prepared(), limits={'height_limit_m':1})['rejections']


def test_nonrepair_constraint_violation_retains_finite_fitness_gradient():
    spec = prepared(constraints=[{'name':'landscaping_pct','type':'Constraint','Requirement':'Greater than','val':99}])
    result = evaluate_candidate(genes(), spec)
    assert result['rejections'] == [] and result['geometry'] is not None
    assert result['outputs'][-1] < 99
    assert result['constraint_violations'][0]['name'] == 'landscaping_pct'


@pytest.mark.parametrize('options', [{'limits':{'bcr_limit_pct':-1}}, {'envelope':{'slanted_polygons':[]}},
                                   {'envelope':{'elevation_source':'failed'}}])
def test_context_validation_rejects_before_enumeration(options):
    from backend.app.modules.design.optimization.evaluator import validate_context
    from backend.app.modules.design.optimization.geometry import CandidateRejected
    with pytest.raises(CandidateRejected):
        validate_context(prepared(), **options)


def source_modules(monkeypatch):
    root = Path('D:/Data/25_ACE/ARR/backend/design/services')
    if not root.exists():
        pytest.skip('Optional original ARR differential source is absent')
    modules = {}
    for name in ('repair_operator','mass_evaluator','mass_renderer'):
        tree = ast.parse((root / f'{name}.py').read_text(encoding='utf-8'))
        tree.body = [node for node in tree.body if not (isinstance(node, ast.ImportFrom) and (node.module or '').startswith('design.'))]
        module = types.ModuleType(f'design.services.{name}')
        module.__dict__.update(wgs84_to_utm=wgs84_to_utm, utm_to_wgs84=utm_to_wgs84)
        if name == 'mass_renderer':
            module.__dict__.update({key: modules['mass_evaluator'].__dict__[key] for key in ('BUILDERS','get_floor_height','_global_idx','_build_mass_polygon_freeform')})
        monkeypatch.setitem(__import__('sys').modules, module.__name__, module)
        exec(compile(tree, str(root/f'{name}.py'), 'exec'), module.__dict__)
        modules[name] = module
    return modules


@pytest.mark.parametrize('floor_count,upper,rotation', [(4,0.8,0),(8,1,23),(2,0.97,80)])
def test_original_differential_supported_fixtures(monkeypatch, floor_count, upper, rotation):
    source = source_modules(monkeypatch)
    spec = prepared()
    values = genes(floors=floor_count, upper=upper)
    values[26][0] = rotation
    candidate = types.SimpleNamespace(get_inputs=lambda: values)
    site = shape(spec['site_polygon'])
    expected = source['mass_evaluator'].evaluate_designs([candidate],site,spec['site_area_m2'],spec['job_spec']['outputs'],'업무시설','additive',enable_repair=True)[0]
    expected_feature = source['mass_renderer'].design_to_geojson(values,site,spec['site_area_m2'],'업무시설','additive',enable_repair=True,outputs_def=spec['job_spec']['outputs'])
    actual = evaluate_candidate(values,spec)
    assert actual['rejections'] == []
    assert actual['outputs'] == pytest.approx(expected, abs=1e-8)
    assert actual['geometry']['properties'] == json.loads(json.dumps(expected_feature['properties']))
    assert shape(actual['geometry']['geometry']).symmetric_difference(shape(expected_feature['geometry'])).area < 1e-14


@pytest.mark.parametrize('constraints,envelope_enabled', [
    ([{'name':'bcr','type':'Constraint','Requirement':'Less than','val':20}],False),
    ([{'name':'far','type':'Constraint','Requirement':'Less than','val':120}],False),
    ([{'name':'height','type':'Constraint','Requirement':'Less than','val':15}],False),
    ([],True),
])
def test_original_differential_repair_limits_and_sunlight(monkeypatch, constraints, envelope_enabled):
    source = source_modules(monkeypatch)
    spec = prepared(constraints=constraints)
    values = genes(width=70,depth=70,floors=8,upper=1)
    envelope = None
    if envelope_enabled:
        ring = mapping(utm_to_wgs84(box(320020,4150020,320060,4150060)))['coordinates'][0]
        envelope = {'slanted_polygons':[{'corners':[[x,y,12] for x,y in ring]}]}
    site = shape(spec['site_polygon'])
    candidate = types.SimpleNamespace(get_inputs=lambda:values)
    expected = source['mass_evaluator'].evaluate_designs([candidate],site,spec['site_area_m2'],spec['job_spec']['outputs'],
                    '업무시설','additive',enable_repair=True,sunlight_envelope=envelope)[0]
    feature = source['mass_renderer'].design_to_geojson(values,site,spec['site_area_m2'],'업무시설','additive',
                    enable_repair=True,outputs_def=spec['job_spec']['outputs'],sunlight_envelope=envelope)
    actual = evaluate_candidate(values,spec,envelope=envelope)
    assert actual['rejections'] == []
    assert actual['outputs'] == pytest.approx(expected,abs=1e-8)
    assert actual['geometry']['properties'] == json.loads(json.dumps(feature['properties']))


def test_disconnected_box_reduction_is_visible():
    values = genes(width=8,depth=8,upper=1)
    for index in range(5):
        values[index*5][0] = (index-2)*12
    result = evaluate_candidate(values,prepared())
    assert result['rejections'] == []
    assert 'disconnected_boxes_to_largest' in result['repair']['actions']


def test_nan_envelope_cannot_reach_height_math():
    envelope = {'slanted_polygons':[{'corners':[[127,37,float('nan')],[127.001,37,10],[127.001,37.001,10]]}]}
    result = evaluate_candidate(genes(),prepared(),envelope=envelope)
    assert result['rejections'][0]['code'] == 'invalid_sunlight_envelope'
    assert result['outputs'] == []


def test_scaled_upper_plate_outside_concave_base_is_not_silently_accepted():
    values = genes(upper=0.8)
    for index in range(5):
        box_values = (-16,0,8,40,0) if index == 0 else (0,-16,40,8,0)
        values[index*5:index*5+5] = [[value] for value in box_values]
    result = evaluate_candidate(values,prepared(),
        limits={'bcr_limit_pct':100,'adjacent_setback_m':0,'road_setback_m':0,'north_setback_m':0})
    assert result['rejections'][0]['code'] == 'unsupported_upper_topology'


def test_small_north_setback_violation_is_clipped_even_below_one_percent():
    from backend.app.modules.design.optimization.repair import resolve_limits, repair_geometry
    limits, _ = resolve_limits([], 3.8, {'adjacent_setback_m':0, 'road_setback_m':0})
    footprint, _, _ = repair_geometry(box(10,10,30,98.51), box(0,0,100,100), 1, limits)
    assert footprint.bounds[3] <= 98.5
