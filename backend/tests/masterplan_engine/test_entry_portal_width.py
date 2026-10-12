import pytest
from shapely.affinity import rotate
from shapely.geometry import LineString, MultiLineString, box, mapping

from backend.app.modules.design.generation.maas.masterplan.validation_circulation import validate_circulation_geometry


@pytest.mark.parametrize('angle', [0, 37])
@pytest.mark.parametrize('segments,expected', [
    ([[(27, 0), (28, 0)]], 1),
    ([[(25, 0), (27, 0)], [(29, 0), (31, 0)]], 2),
    ([[(25, 0), (31, 0)]], 6),
])
def test_approach_width_is_limited_by_continuous_road_opening(angle, segments, expected):
    road = LineString(segments[0]) if len(segments) == 1 else MultiLineString(segments)
    entrance = box(25, 0, 31, 10)
    features = [{'geometry': mapping(rotate(g, angle, origin=(0, 0))),
                 'properties': {'layer': layer, 'role': role, 'level': 0}}
                for g, layer, role in [(road, 'road_frontage', None),
                                     (entrance, 'vehicular_access', 'road_to_ramp_connector')]]
    checks = validate_circulation_geometry(features, {'aisle_width_m': 6})['checks']
    width = next(c for c in checks if c['id'] == 'entry_approach_width')
    assert width['measured'] == pytest.approx(expected, abs=0.01)
    assert width['status'] == ('passed' if expected == 6 else 'failed')
