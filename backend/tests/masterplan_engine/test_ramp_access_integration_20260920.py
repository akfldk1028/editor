"""The interior approach must survive planner export and reserve the ground."""
from shapely.geometry import Polygon, box, LineString, mapping, shape
from test_masterplan_engine import request
from test_ramp_fitting_20260920 import rules
import pytest


@pytest.mark.parametrize('strategy', ['basement', 'mixed'])
def test_interior_connector_is_exported_and_reserved_before_ground_packing(monkeypatch, strategy):
    from backend.app.modules.design.generation.maas.masterplan import planner
    data = request(10, strategy=strategy)
    data.update(site=mapping(box(0,0,28,52)), buildable=mapping(box(0,0,28,52)),
                basement_boundary=mapping(box(0,0,28,52)), core=None,
                footprint=mapping(box(9,12,28,52)),
                frontage=mapping(LineString([(12,0),(20,0)])))
    data['rules'].update(rules())
    data['options'].update(max_basement_levels=1, ramp_shape='straight')
    data['options']['target_surface_stalls']=5
    hosts = []
    def record_host(envelope, *args, **kwargs):
        hosts.append(envelope)
        return {'stalls':[], 'drive':Polygon(), 'provided':0, 'accessible':0, 'search_count':0}
    # Isolate serialization/reservation from parking ranking, whose geometry
    # is covered by the engine tests. Real ramp and validator run here.
    monkeypatch.setattr(planner, 'pack_level', record_host)
    monkeypatch.setattr(planner, 'row_candidates', lambda *a, **k: [])
    # Basement packing moved behind its own solver; preserve this test's
    # intentionally empty parking isolation at that boundary as well.
    from backend.app.modules.design.generation.maas.masterplan import basement_layout
    monkeypatch.setattr(basement_layout, 'pack_level', record_host)
    monkeypatch.setattr(basement_layout, 'row_candidates', lambda *a, **k: [])
    evaluated = []
    real_validate = planner.validate_plan
    def capture(req, candidate):
        evaluated.append(candidate)
        return real_validate(req, candidate)
    monkeypatch.setattr(planner, 'validate_plan', capture)
    out = planner.plan_site(data)
    # Empty mocked parking makes the surface alternative win in mixed mode;
    # inspect the actual exported basement candidate in that case.
    subject = out if strategy=='basement' else next(c for c in evaluated if any(
        f['properties'].get('role')=='road_to_ramp_connector' for f in c['features']))
    connectors = [shape(f['geometry']) for f in subject['features']
                  if f['properties'].get('role')=='road_to_ramp_connector']
    assert connectors
    connector = connectors[0]
    assert connector.distance(shape(data['frontage'])) < 1e-7
    if strategy=='mixed':
        assert any(h.intersection(connector).area < 1e-7 for h in hosts[1:])
    assert any(c['id']=='ramp_road_connection' and c['status']=='passed'
               for c in subject['validation']['checks'])
    assert out['mass_feedback']['demand']['shortfall_stalls'] == 10
    assert out['mass_feedback']['mass_context']['automatic_mass_change'] is False
    assert any('surface parking design target is 5' in item for item in out['blocking'])
    assert out['status']=='needs_revision'
