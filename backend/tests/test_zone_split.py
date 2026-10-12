"""zone_split: the one rule for what is a 용도지역 part of a parcel and what is a boundary drawn at another scale.

Synthetic parcels in metres (no projection): a 50 m × 50 m parcel at the origin. Zone pieces are given already
clipped to the parcel, as both zone_geometry copies hand them over."""
import json

import pytest
from shapely.geometry import LineString, Polygon, box

from backend.app.modules.land.reference.services import zone_split as module
from backend.app.modules.land.reference.services.zone_split import (
    BOUNDARY_TOLERANCE, ZONE_OVERLAP, exclusive_zone_names, polygonal, split_parcel)

PARCEL = box(0, 0, 50, 50)          # 2,500 m2
AREA = PARCEL.area


def clipped(*zones):
    """{name: [piece ∩ parcel]} from (name, polygon) pairs — what zone_geometry builds from the WFS features."""
    return {name: [geometry.intersection(PARCEL)] for name, geometry in zones}


def total(split):
    return sum(split.areas.values()) + split.uncovered_m2


def test_a_hair_of_another_zone_inside_the_covering_zone_is_an_overlap_not_a_part():
    # 684-1's shape: A covers the whole parcel; B is a 0.1 m strip along one edge, entirely inside A's polygon.
    split = split_parcel(PARCEL, clipped(('A', box(-10, -10, 60, 60)), ('B', box(49.9, -10, 60, 60))), small_part_m2=330)
    assert split.areas == pytest.approx({'A': 2500.0})
    assert split.zones == ['A']
    assert split.uncovered_m2 == pytest.approx(0.0, abs=1e-6)
    (sliver,) = split.excluded_slivers
    assert (sliver.zone, sliver.reason, sliver.folded_into) == ('B', ZONE_OVERLAP, 'A')
    assert sliver.area_m2 == pytest.approx(5.0)
    assert sliver.width_m == pytest.approx(0.0996, abs=1e-3)
    assert sliver.share == pytest.approx(0.002)
    assert total(split) == pytest.approx(AREA)
    assert '제84조 분할에서 제외' in split.notes()[0] and 'B' in split.notes()[0]


def test_a_genuine_split_is_kept_whole():
    split = split_parcel(PARCEL, clipped(('A', box(-10, -10, 40, 60)), ('B', box(40, -10, 60, 60))), small_part_m2=330)
    assert split.areas == pytest.approx({'A': 2000.0, 'B': 500.0})
    assert split.excluded_slivers == ()
    assert split.zones == ['A', 'B']
    assert total(split) == pytest.approx(AREA)


def test_two_zones_overlapping_each_other_resolve_to_the_one_covering_more():
    # A covers x 0–30, B covers x 25–50: the 5 m band (250 m2) is claimed by both and goes to A (1,500 > 1,250).
    split = split_parcel(PARCEL, clipped(('A', box(-10, -10, 30, 60)), ('B', box(25, -10, 60, 60))), small_part_m2=330)
    assert split.areas == pytest.approx({'A': 1500.0, 'B': 1000.0})
    (sliver,) = split.excluded_slivers
    assert (sliver.zone, sliver.reason, sliver.folded_into) == ('B', ZONE_OVERLAP, 'A')
    assert sliver.area_m2 == pytest.approx(250.0)
    assert total(split) == pytest.approx(AREA)


def test_uncovered_ground_is_reported_never_invented():
    split = split_parcel(PARCEL, clipped(('A', box(-10, -10, 30, 60))), small_part_m2=330)
    assert split.areas == pytest.approx({'A': 1500.0})
    assert split.uncovered_m2 == pytest.approx(1000.0)
    assert split.excluded_slivers == ()
    assert '미피복 1000.00' in split.notes()[0]


def test_a_thin_exclusive_strip_is_boundary_tolerance_folded_into_the_largest_zone():
    # B owns a 0.3 m × 50 m strip (15 m2 = 0.6 %) that A does not cover: a drawing offset, not a 제84조 part.
    split = split_parcel(PARCEL, clipped(('A', box(-10, -10, 49.7, 60)), ('B', box(49.7, -10, 60, 60))), small_part_m2=330)
    assert split.areas == pytest.approx({'A': 2500.0})
    (sliver,) = split.excluded_slivers
    assert (sliver.zone, sliver.reason, sliver.folded_into) == ('B', BOUNDARY_TOLERANCE, 'A')
    assert sliver.area_m2 == pytest.approx(15.0)
    assert sliver.width_m == pytest.approx(0.298, abs=1e-3)
    assert total(split) == pytest.approx(AREA)


def test_a_small_green_part_wide_enough_to_be_ground_stays_a_part_and_combine_limits_branches_on_it():
    from backend.app.modules.land.reference.services import zoning_mapper
    # 자연녹지 250 m2 (10 %, 5 m wide): a real part, under the 330 m2 small-part size → 제84조제1항 weighting.
    split = split_parcel(PARCEL, clipped(('제2종일반주거지역', box(-10, -10, 45, 60)), ('자연녹지지역', box(45, -10, 60, 60))), small_part_m2=330)
    assert split.areas == pytest.approx({'제2종일반주거지역': 2250.0, '자연녹지지역': 250.0})
    assert split.excluded_slivers == ()
    zones = [zoning_mapper.lookup('제2종일반주거지역'), zoning_mapper.lookup('자연녹지지역')]
    assert all(zones), 'zoning catalog must know both zones'
    weighted = zoning_mapper.combine_limits(zones, split.areas)
    assert weighted['overlap']['branch'] == '제84조제1항'
    assert weighted['overlap']['smallest_part']['area_m2'] == pytest.approx(250.0)
    assert weighted['overlap']['total_area_m2'] == pytest.approx(AREA)
    # 400 m2 of green (8 m wide) is over the size: 제84조제3항, each part its own rules.
    bigger = split_parcel(PARCEL, clipped(('제2종일반주거지역', box(-10, -10, 42, 60)), ('자연녹지지역', box(42, -10, 60, 60))), small_part_m2=330)
    assert zoning_mapper.combine_limits(zones, bigger.areas)['overlap']['branch'] == '제84조제3항'


def test_a_strip_larger_than_the_small_part_size_is_never_folded_whatever_its_width():
    # A 0.9 m × 400 m strip on a 40,000 m2 parcel (360 m2 = 0.9 %) passes share and width but is over 330 m2.
    parcel = box(0, 0, 400, 100)
    split = split_parcel(parcel, {'A': [box(0, 0, 400, 99.1)], 'B': [box(0, 99.1, 400, 100)]}, small_part_m2=330)
    assert split.areas == pytest.approx({'A': 39640.0, 'B': 360.0})
    assert split.excluded_slivers == ()
    without_size = split_parcel(parcel, {'A': [box(0, 0, 400, 99.1)], 'B': [box(0, 99.1, 400, 100)]})
    assert without_size.areas == pytest.approx({'A': 40000.0})


def test_zero_area_pieces_lines_and_collections_are_dropped_not_slivers():
    collection = LineString([(0, 0), (50, 0)]).buffer(0)      # an empty/zero-area geometry
    split = split_parcel(PARCEL, {'A': [PARCEL], 'B': [LineString([(0, 0), (50, 50)])], 'C': [collection], 'D': []}, small_part_m2=330)
    assert split.areas == pytest.approx({'A': 2500.0})
    assert split.excluded_slivers == ()
    assert polygonal(LineString([(0, 0), (1, 1)])).is_empty and polygonal(None).is_empty


def test_the_largest_zone_is_never_tolerance_and_an_empty_parcel_is_empty():
    tiny = box(0, 0, 0.5, 10)                                  # a 5 m2 parcel, 0.5 m wide: one zone, kept
    split = split_parcel(tiny, {'A': [tiny]}, small_part_m2=330)
    assert split.areas == pytest.approx({'A': 5.0}) and split.excluded_slivers == ()
    assert split_parcel(Polygon(), {'A': [PARCEL]}).areas == {}


def test_exclusive_zone_names_drops_only_use_zones_that_lost_their_ground():
    names = ['제2종일반주거지역', '자연녹지지역', '지구단위계획구역', '과밀억제권역']
    use_zone = lambda name: name.endswith('지역') and name != '권역'  # the catalog's shape: 용도지역 only
    kept, removed = exclusive_zone_names({'제2종일반주거지역': 2500.0}, names, use_zone)
    assert kept == ['제2종일반주거지역', '지구단위계획구역', '과밀억제권역']
    assert removed == ['자연녹지지역']
    assert exclusive_zone_names(None, names, use_zone) == (names, [])


def test_with_removed_explains_a_removed_zone_the_slivers_do_not():
    from backend.app.modules.land.reference.services.zone_split import with_removed
    split = split_parcel(PARCEL, clipped(('A', box(-10, -10, 60, 60)), ('B', box(49.9, -10, 60, 60))), small_part_m2=330)
    payload = with_removed(split.to_dict(), ['B', 'C'])        # C: in the official list, never inside the parcel
    assert payload['removed_zones'] == ['B', 'C']
    assert len(payload['notes']) == 2 and payload['notes'][0].startswith('B:') and payload['notes'][1].startswith('C:')
    assert '겹치는 면적이 없어' in payload['notes'][1]
    assert with_removed(split.to_dict(), [])['notes'] == split.notes()


def test_to_dict_is_json_with_thresholds_and_notes():
    split = split_parcel(PARCEL, clipped(('A', box(-10, -10, 60, 60)), ('B', box(49.9, -10, 60, 60))), small_part_m2=330)
    payload = json.loads(json.dumps(split.to_dict(), ensure_ascii=False))
    assert payload['version'] == module.SPLIT_VERSION and payload['method'] == module.METHOD
    assert payload['areas_m2'] == {'A': 2500.0}
    assert payload['excluded_slivers'][0]['zone'] == 'B' and payload['excluded_slivers'][0]['reason'] == ZONE_OVERLAP
    assert payload['thresholds'] == {'max_share': module.BOUNDARY_TOLERANCE_MAX_SHARE, 'max_width_m': module.BOUNDARY_TOLERANCE_MAX_WIDTH_M,
                                     'basis': module.TOLERANCE_BASIS}
    assert payload['notes'] == split.notes() and len(payload['notes']) == 1


def test_both_zone_geometry_copies_agree_through_the_projection():
    from backend.app.modules.land import zone_geometry as short_copy
    from backend.app.modules.land.projection import utm_to_wgs84, wgs84_to_utm
    from backend.app.modules.land.reference.services import zone_geometry as reference_copy
    from shapely.affinity import translate
    from shapely.geometry import mapping
    place = lambda geometry: utm_to_wgs84(translate(geometry, xoff=300000, yoff=4150000))
    parcel = place(PARCEL)
    features = [{'properties': {'uname': 'A'}, 'geometry': mapping(place(box(-10, -10, 60, 60)))},
                {'properties': {'uname': 'B'}, 'geometry': mapping(place(box(49.9, -10, 60, 60)))}]
    short = short_copy.zone_split(parcel, features)
    reference = reference_copy.zone_split(parcel, features, to_utm=wgs84_to_utm)
    assert short.to_dict() == reference.to_dict()
    assert list(short.areas) == ['A'] and short.areas['A'] == pytest.approx(2500.0, rel=1e-4)
    assert short_copy.zone_areas(parcel, features) == short.areas
    assert short.excluded_slivers[0].zone == 'B' and short.excluded_slivers[0].width_m == pytest.approx(0.1, abs=0.01)
