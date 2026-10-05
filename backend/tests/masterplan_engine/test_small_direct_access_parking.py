from shapely.geometry import box, LineString, Polygon
from backend.app.modules.design.generation.maas.masterplan.rows import row_candidates
from backend.app.modules.design.generation.maas.masterplan.bounded_packing import pack_level, _width_connected

RULES = {'stall_width_m': 2.5, 'stall_length_m': 5., 'accessible_width_m': 3.3,
         'accessible_length_m': 5., 'aisle_width_m': 6.}


def test_two_bay_direct_road_access_does_not_require_a_third_bay_or_redundant_spine():
    site = box(0, 0, 6, 11)
    road = LineString([(0, 5), (0, 11)])
    proposals = row_candidates(site, site, Polygon(), Polygon(), road, None, RULES, 2, 0, field='single')
    assert proposals
    best = max(proposals, key=lambda p: p['provided'])
    assert best['provided'] == 2
    assert _width_connected(best, [road], 6.)
    assert all(s['polygon'].intersection(best['drive']).area < 1e-6 for s in best['stalls'])


def test_small_packer_uses_direct_aisle_when_separate_spine_cannot_fit():
    site = box(0, 0, 6, 11)
    road = LineString([(0, 5), (0, 11)])
    result = pack_level(site, [road], RULES, 2)
    assert result['provided'] == 2
    assert _width_connected(result, [road], 6.)


def test_external_entrance_corridor_stays_clear_of_small_field_bays():
    site = box(0, 0, 12, 17)
    road = LineString([(0, 0), (6, 0)])
    proposals = row_candidates(site, site, Polygon(), Polygon(), road, None, RULES, 4, 0, field='single')
    assert proposals
    assert all(s['polygon'].intersection(p['drive']).area < 1e-6 for p in proposals for s in p['stalls'])
