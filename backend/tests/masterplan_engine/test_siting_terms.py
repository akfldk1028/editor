from shapely.geometry import LineString, box, mapping

from backend.app.modules.design.generation.maas.masterplan.siting_terms import (
    building_frontage_score, gates_on_front, road_openings)

# A 60 x 40 m lot: the front (wide) road along the north edge, a lesser road along the east edge.
FRONT = LineString([(0, 40), (60, 40)])
EAST = LineString([(60, 0), (60, 40)])


def request(frontage=(FRONT, EAST), front=FRONT, prohibited=None):
    from shapely.ops import unary_union
    req = {'frontage': mapping(unary_union(list(frontage))), 'front_frontage': mapping(front) if front is not None else None}
    if prohibited is not None:
        req['vehicle_prohibited'] = mapping(prohibited)
    return req


def drive(*polys):
    return [{'geometry': mapping(p), 'properties': {'layer': 'parking_aisle', 'level': 0}} for p in polys]


def test_one_shared_gate_counts_one_opening_and_a_separate_ramp_gate_two():
    shared = drive(box(20, 0, 60, 6))
    split = drive(box(20, 0, 60, 6), box(54, 20, 60, 26))
    assert road_openings(request(), shared) == 1
    assert road_openings(request(), split) == 2


def test_a_gate_on_the_front_road_counts_only_when_another_road_exists():
    on_front = drive(box(10, 34, 16, 40))
    assert gates_on_front(request(), on_front) == 1
    assert gates_on_front(request(frontage=(FRONT,)), on_front) == 0  # the front is the only road
    assert gates_on_front(request(), drive(box(54, 0, 60, 6))) == 0


def test_the_building_gains_on_no_vehicle_frontage_and_loses_on_gate_frontage():
    against_front = box(10, 22, 50, 38)      # 2 m back from the front road
    against_east = box(40, 5, 58, 35)        # 2 m back from the lesser road
    assert building_frontage_score(request(), against_front) > 0
    assert building_frontage_score(request(), against_east) < 0
    assert building_frontage_score(request(), against_front) > building_frontage_score(request(), against_east)


def test_declared_no_access_interval_is_frontage_the_building_may_take():
    req = request(frontage=(EAST,), front=None, prohibited=LineString([(60, 20), (60, 40)]))
    assert building_frontage_score(req, box(40, 22, 58, 38)) > 0
    assert building_frontage_score(req, box(40, 2, 58, 18)) < 0
