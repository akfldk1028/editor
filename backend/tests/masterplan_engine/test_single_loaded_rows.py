"""A narrow parcel can fit one loaded row without fitting a double module."""
from shapely.geometry import box, LineString, Polygon
from backend.app.modules.design.generation.maas.masterplan.rows import row_candidates


def test_narrow_ground_keeps_one_row_and_full_width_road_connected_aisle():
    site = box(0,0,24,11)
    road = LineString([(0,0),(0,11)])
    rules = {'stall_width_m':2.5, 'stall_length_m':5., 'accessible_width_m':3.3,
             'accessible_length_m':5., 'aisle_width_m':6.}
    candidates = row_candidates(site, site, Polygon(), Polygon(), road, None, rules, 8, 1)
    assert candidates
    best = max(candidates, key=lambda c:c['provided'])
    assert best['provided'] >= 5
    assert best['accessible'] >= 1
    assert site.buffer(1e-7).covers(best['drive'])
    assert best['drive'].distance(road) < 1e-7
    assert all(site.buffer(1e-7).covers(s['polygon']) and best['drive'].buffer(1e-7).covers(s['front'])
               and s['polygon'].intersection(best['drive']).area<1e-7 for s in best['stalls'])
