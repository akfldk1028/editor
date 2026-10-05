from shapely.geometry import box, Polygon
from backend.app.modules.design.generation.maas.masterplan.rows import _tile_bands
import pytest


@pytest.mark.parametrize('accessible,acc_length,expanded,expanded_needed',
                         [(0, 5., (2.6, 5.2), 30), (30, 6., None, 0)])
def test_tiled_pitch_reserves_actual_back_to_back_bay_depth(accessible, acc_length, expanded, expanded_needed):
    plan = _tile_bands(box(0, 0, 40, 100), Polygon(), 6., 6., 2.5, 5., 3.3, acc_length,
                       0., 40., 0, None, accessible, expanded, expanded_needed, ring=True, required=60)
    assert plan and plan['bands'] > 1
    assert any(s['length_m'] > 5 for s in plan['stalls'])
    for i, stall in enumerate(plan['stalls']):
        assert all(stall['polygon'].intersection(other['polygon']).area < 1e-6
                   for other in plan['stalls'][i+1:])
