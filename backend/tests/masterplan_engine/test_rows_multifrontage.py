import pytest
from shapely.geometry import LineString, MultiLineString, Point, box

from backend.app.modules.design.generation.maas.masterplan.rows import row_candidates


RULES = {'stall_width_m': 2.5, 'stall_length_m': 5, 'accessible_width_m': 3.3,
         'accessible_length_m': 5, 'aisle_width_m': 6}


@pytest.mark.parametrize('turn_radius', [None, 1.0])
@pytest.mark.parametrize('constraint', ['corner', 'prohibited'])
def test_rejected_first_frontage_keeps_valid_opposite_entry(constraint, turn_radius):
    site = box(0, 0, 30, 30)
    ground = box(5, 0, 25, 30)
    footprint = site.difference(ground)
    top = LineString([(0, 30), (30, 30)])
    frontage = MultiLineString([top, [(0, 0), (11, 0)], [(19, 0), (30, 0)]])
    options = ({'entry_clearance_m': 4} if constraint == 'corner' else
               {'prohibited': LineString([(0, 0), (30, 0)])})
    rows = row_candidates(site, ground, footprint, None, frontage, frontage, RULES,
                          30, 0, allowed_angles=[0], turn_radius_m=turn_radius, **options)
    assert rows, 'Rejecting the bottom entrance must leave the valid top route available'
    assert max(r['provided'] for r in rows) >= 10
    for row in rows:
        entrance = row['entrance']
        assert entrance.distance(top) <= 1e-6
        if constraint == 'corner':
            assert all(entrance.distance(Point(line.coords[i])) >= 4 - 1e-6
                       for line in frontage.geoms for i in (0, -1))
        else:
            assert entrance.distance(options['prohibited']) > 0.05
