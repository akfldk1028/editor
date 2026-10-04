import importlib
import json
from pathlib import Path

import pytest
from shapely.geometry import shape


FIXTURE = json.loads((Path(__file__).parent / 'fixtures/land_geometry_source.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('case', FIXTURE['setbacks'], ids=lambda case: case['name'])
def test_setbacks_equal_preserved_source_response(case):
    module = importlib.import_module('backend.app.modules.regulations.setbacks')
    actual = module.compute_setback_lines(case['parcel'], case['regulations'],
        road_frontages=case['road_frontages'], neighbor_parcels=case['neighbor_parcels'])
    assert json.loads(json.dumps(actual, allow_nan=False)) == case['expected']


@pytest.mark.parametrize('case', FIXTURE['zone_areas'], ids=lambda case: case['name'])
def test_zone_intersections_equal_source_without_double_counting(case):
    module = importlib.import_module('backend.app.modules.land.zone_geometry')
    projection = importlib.import_module('backend.app.modules.land.projection')
    polygon = shape(case['parcel'])
    actual = module.zone_areas(polygon, case['features'])
    assert actual == pytest.approx(case['expected'], abs=1e-7)
    assert sum(actual.values()) == pytest.approx(projection.wgs84_to_utm(polygon).area, abs=1e-5)
    assert set(actual) == {'A', 'B'}


def test_datum_true_requires_explicit_service():
    module = importlib.import_module('backend.app.modules.regulations.setbacks')
    with pytest.raises(ValueError, match='service'):
        module.compute_setback_lines(FIXTURE['setbacks'][0]['parcel'], {}, compute_datum=True)


def test_projection_roundtrip_preserves_holes_and_largest_net_area():
    projection = importlib.import_module('backend.app.modules.land.projection')
    polygon = shape(FIXTURE['setbacks'][1]['parcel'])
    restored = projection.utm_to_wgs84(projection.wgs84_to_utm(polygon))
    assert restored.equals_exact(polygon, tolerance=1e-10)
    assert len(restored.interiors) == 1
    multi = FIXTURE['setbacks'][2]['parcel']
    assert projection.geojson_to_polygon(multi).equals(max(shape(multi).geoms, key=lambda part: part.area))
