"""Unselected ramp/slab attempts cannot claim the winning surface field is impossible."""
from shapely.geometry import Polygon

from backend.app.modules.design.generation.maas.masterplan import planner
from test_masterplan_engine import request


def test_rejected_split_stays_in_alternative_diagnostics(monkeypatch):
    data = request(required=4, strategy='mixed')
    data['options']['max_basement_levels'] = 1
    # Keep the first real ground packing. Bound the expensive alternative solver
    # to one actual ramp with no available surface/basement packing beside it.
    real_pack = planner.pack_level
    calls = []
    def pack(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            return real_pack(*args, **kwargs)
        return {'stalls': [], 'drive': Polygon(), 'provided': 0, 'accessible': 0, 'search_count': 1}
    real_ramps = planner.ramp_candidates
    monkeypatch.setattr(planner, 'pack_level', pack)
    monkeypatch.setattr(planner, 'ramp_candidates', lambda *a, **k: real_ramps(*a, **k)[:1])
    monkeypatch.setattr(planner, 'curved_ramp_candidates', lambda *a, **k: [])
    monkeypatch.setattr(planner, 'row_candidates', lambda *a, **k: [])
    monkeypatch.setattr(planner, 'slab_envelopes', lambda *a, **k: [])
    monkeypatch.setattr(planner, 'solve_basement_level', lambda *a, **k: None)
    result = planner.plan_site(data)
    assert len(calls) > 1, 'The unsuccessful ramp alternative must actually run'
    assert result['metrics']['provided_parking_stalls'] == 4
    assert result['validation']['geometry_status'] == 'passed'
    assert not any(s.startswith('surface/basement split does not fit') for s in result['blocking'])
    reviews = [s for alt in result['alternatives'] for s in alt.get('pending_reviews', [])]
    assert any(s.startswith('surface/basement split does not fit') for s in reviews)
