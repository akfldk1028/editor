import math
import pytest
from shapely.geometry import LineString
from backend.app.modules.design.generation.maas.masterplan.ramps import ramp_profile
from backend.app.modules.design.generation.maas.masterplan.rows import _curved_at_aisle_end, _curved_off_aisle


def spec():
    return ramp_profile({'ramp_max_slope': .14, 'ramp_width_m': 6.5,
                         'transition_slope': .07, 'transition_length_m': 3.,
                         'aisle_width_m': 6.}, 3.3)


@pytest.mark.parametrize('at_end', [True, False])
def test_row_curve_landings_are_flat_and_centerline_preserves_grade_breaks(at_end):
    s = spec()
    built = (_curved_at_aisle_end(0, 6, 1, 1, s, 5, 0, 25) if at_end else
             _curved_off_aisle(0, 0, 6, 1, 1, s, 5))
    poly, upper, lower, center, used, radius = built
    assert upper.area == pytest.approx(6 * 6.5, abs=1e-6)
    assert lower.area == pytest.approx(6 * 6.5, abs=1e-6)
    assert center.length == pytest.approx(s['length_m'], abs=1e-8)
    distances = [0.]
    coords = list(center.coords)
    for a, b in zip(coords, coords[1:]):
        distances.append(distances[-1] + math.dist(a[:2], b[:2]))
    for station in s['profile']:
        i = min(range(len(distances)), key=lambda i: abs(distances[i]-station['distance_m']))
        assert distances[i] == pytest.approx(station['distance_m'], abs=1e-8)
        assert coords[i][2] == pytest.approx(station['z_m'], abs=1e-8)


def test_asymmetric_shallow_turn_keeps_radius_and_full_drop():
    s = spec()
    built = _curved_at_aisle_end(0, 6, 1, -1, s, 5, 0, 25, lead_fraction=0., turn_deg=45.)
    assert built is not None
    poly, upper, lower, center, used, radius = built
    assert center.coords[-1][2] == pytest.approx(-3.3)
    assert center.length == pytest.approx(s['length_m'], abs=1e-8)
    assert upper.area == pytest.approx(39., abs=1e-8)
    from backend.app.modules.design.generation.maas.masterplan.validation import _min_turn_radius
    assert _min_turn_radius([p[:2] for p in center.coords]) >= radius - 1e-6


def test_grade_station_pruning_does_not_remove_a_real_sharp_corner():
    from backend.app.modules.design.generation.maas.masterplan.validation import _min_turn_radius
    # Straight grade stations disappear; the 90 degree turn must remain.
    coords = [(0, 0), (1, 0), (2, 0), (2, 1), (2, 2)]
    assert _min_turn_radius(coords) == pytest.approx(math.sqrt(2))
