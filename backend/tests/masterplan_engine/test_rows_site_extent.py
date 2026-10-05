"""A road connection cannot stop at an unrelated fixed world distance."""
from shapely.geometry import box, LineString, Polygon
from shapely.affinity import scale
import pytest
from backend.app.modules.design.generation.maas.masterplan import rows
from backend.app.modules.design.generation.maas.masterplan.bounded_packing import _width_connected


@pytest.mark.parametrize('road_at_top', [False, True])
def test_far_parking_field_uses_full_actual_site_extent_for_road_connection(monkeypatch, road_at_top):
    site = box(0, 0, 40, 500)
    occupied = box(6, 0, 40, 450)
    road = LineString([(0, 0), (6, 0)])
    if road_at_top:
        occupied = scale(occupied, xfact=1, yfact=-1, origin=(0, 250))
        road = scale(road, xfact=1, yfact=-1, origin=(0, 250))
    ground = site.difference(occupied)
    rules = {'stall_width_m': 2.5, 'stall_length_m': 5., 'accessible_width_m': 3.3,
             'accessible_length_m': 5., 'aisle_width_m': 6.}
    # Isolate the corridor geometry; rotated alternatives must not hide a
    # failure to connect this feasible horizontal field to its southern road.
    monkeypatch.setattr(rows, 'orientation_candidates', lambda *args: [0.])
    proposals = rows.row_candidates(site, ground, occupied, Polygon(), road, None, rules, 40, 0)
    assert proposals
    best = max(proposals, key=lambda c: c['provided'])
    assert best['provided'] > 0
    assert all(s['polygon'].bounds[3] <= 50+1e-6 if road_at_top else
               s['polygon'].bounds[1] >= 450-1e-6 for s in best['stalls'])
    assert best['drive'].distance(road) < 1e-6
    assert ground.buffer(1e-6).covers(best['drive'])
    assert _width_connected(best, [road], 6.)


def test_long_narrow_field_can_supply_demand_beyond_seventeen_bands():
    result = rows._tile_bands(box(0, 0, 20, 600), Polygon(), 5, 6, 2.5, 5, 3.3, 5,
                              0, 20, 0, box(0, 0, 6, 11), 0, None, 0,
                              ring=True, required=200)
    assert result is not None
    assert result['bands'] > 17
    assert len(result['stalls']) >= 200


def test_demand_budget_discovers_usable_bands_near_far_ground_edge():
    # The first 950 m has a cross aisle but no bay-width field. Valid modules
    # exist only near the far edge, well outside the former +/-8 offsets.
    ground = box(0, 0, 6, 1000).union(box(0, 950, 20, 1000))
    result = rows._tile_bands(ground, Polygon(), 5, 6, 2.5, 5, 3.3, 5,
                              0, 20, 0, box(0, 0, 6, 1000), 0, None, 0,
                              ring=False, required=12)
    assert result is not None
    assert len(result['stalls']) >= 12
    assert all(s['polygon'].bounds[1] >= 950 for s in result['stalls'])
    assert result['bands'] <= 17  # demand-limited sampling, not a kilometre sweep
