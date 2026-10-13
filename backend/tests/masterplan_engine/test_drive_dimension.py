import json
from pathlib import Path

from backend.app.modules.design.generation.maas.masterplan.planner import plan_site
from backend.app.modules.design.generation.maas.masterplan.validation import validate_plan


def fixture():
    return json.loads((Path(__file__).parent/'fixtures/real_903_validation_overlay.json').read_text(encoding='utf8'))


def test_generated_drive_serializes_area_without_clipping_lines():
    f = fixture()
    result = plan_site(f['request'])
    aisles = [v for v in result['features'] if v['properties']['layer']=='parking_aisle']
    assert aisles
    assert all(v['geometry']['type'] in ('Polygon','MultiPolygon') for v in aisles)


def test_independent_validator_rejects_mixed_drive_without_crashing():
    f = fixture()
    result = {'features': [{'type':'Feature', 'properties':{'layer':'parking_aisle','level':0}, 'geometry':f['drive']}]}
    checked = validate_plan(f['request'],result)
    assert checked['geometry_status']=='failed'
    assert any(c['id'].startswith('geometry_areal:parking_aisle') and c['status']=='failed' for c in checked['checks'])


def test_invalid_multipart_drive_is_repaired_before_union(monkeypatch):
    from shapely.geometry import MultiPolygon, Polygon, box, shape
    from backend.app.modules.design.generation.maas.masterplan import planner
    invalid = MultiPolygon([Polygon([(0,0),(2,2),(0,2),(2,0),(0,0)]), box(4,0,5,1)])
    packed = {'drive':invalid,'entrance':None,'stalls':[],'provided':0,'accessible':0,'search_count':1,'score':0,'terms':{}}
    monkeypatch.setattr(planner,'row_candidates',lambda *a,**k:[packed])
    monkeypatch.setattr(planner,'pack_level',lambda *a,**k:packed)
    result = planner.plan_site(fixture()['request'])
    aisles = [shape(f['geometry']) for f in result['features'] if f['properties']['layer']=='parking_aisle']
    assert aisles and all(g.is_valid and g.geom_type in ('Polygon','MultiPolygon') for g in aisles)
