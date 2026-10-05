"""A basement floor carries a declared programme, and a ramp may turn.

Both expectations come from the reference scheme's own 지하1층 평면도 (고산동 주민센터 ALT1/ALT2):
the underground floor is 44 % non-parking, and the ramp is a 90 degree curve whose band is exactly
the width 주차장법 시행규칙 제6조제1항제5호다목 sets for two lanes on a curve.
"""
import sys

import pytest
from shapely.geometry import LineString, Polygon, box, mapping, shape


from test_masterplan_engine import engine, request  # noqa: E402

PROGRAMME = [{"name": "기계실", "area_m2": 120.0, "kind": "plant"},
             {"name": "전기실", "area_m2": 60.0, "kind": "plant"},
             {"name": "창고", "area_m2": 40.0, "kind": "storage"}]
CURVED_RULES = {"curved_ramp_width_m": 6.5, "curved_ramp_max_slope": 0.14, "curve_min_inner_radius_m": 6.0}


def _layer(result, layer, level=None):
    return [f for f in result["features"] if f["properties"]["layer"] == layer
            and (level is None or f["properties"].get("level") == level)]


def _checks(result):
    return {c["id"]: c for c in result["validation"]["checks"]}


def test_declared_basement_programme_is_reserved_and_no_stall_stands_in_it():
    data = request(12)
    data["options"]["basement_program"] = PROGRAMME
    result = engine()(data)
    zones = _layer(result, "basement_plant_zone")
    assert zones, result.get("blocking")
    reserved = sum(shape(f["geometry"]).area for f in zones)
    assert reserved + 1e-6 >= sum(r["area_m2"] for r in PROGRAMME)
    rooms = _layer(result, "basement_room")
    assert {f["properties"]["name"] for f in rooms} == {r["name"] for r in PROGRAMME}
    zone = shape(zones[0]["geometry"])
    for stall in _layer(result, "parking_stall"):
        assert shape(stall["geometry"]).intersection(zone).area <= 1e-6
    checks = _checks(result)
    assert checks["plant_zone_clear:-1"]["status"] == "passed"
    assert checks["plant_zone_area:-1"]["status"] == "passed"


def test_an_undeclared_basement_programme_is_reported_rather_than_packed_with_stalls():
    result = engine()(request(12))
    assert not _layer(result, "basement_plant_zone")
    assert any("basement programme" in str(b) for b in result["blocking"]), result["blocking"]


def test_the_programme_costs_stalls_it_does_not_come_for_free():
    """A floor that has to hold plant rooms holds fewer cars - the area is taken, not shared."""
    below = lambda r: len([f for f in _layer(r, "parking_stall") if f["properties"]["level"] < 0])  # noqa: E731
    plain = engine()(request(60))
    data = request(60)
    data["options"]["max_basement_levels"] = 1
    data["options"]["basement_program"] = [{"name": "기계실", "area_m2": 1400.0}]
    plain1 = request(60)
    plain1["options"]["max_basement_levels"] = 1
    withprog = engine()(data)
    assert below(withprog) < below(engine()(plain1)), below(withprog)


def test_curved_ramp_keeps_the_rules_inner_radius_and_width():
    from backend.app.modules.design.generation.maas.masterplan.ramps import curved_ramp_candidates

    rules = {**request()["rules"], **CURVED_RULES}
    site = box(0, 0, 80, 80)
    candidates = curved_ramp_candidates(site, LineString([(0, 0), (80, 0)]), Polygon(), rules, 3.3, limit=6)
    assert candidates, "no curved ramp was proposed on an open site"
    for candidate in candidates:
        assert candidate["width_m"] == CURVED_RULES["curved_ramp_width_m"]
        assert candidate["inner_radius_m"] + 1e-9 >= CURVED_RULES["curve_min_inner_radius_m"]
        # the band is the run times the width, so the plan carries the length the grade needs
        assert candidate["polygon"].area == pytest.approx(candidate["length_m"] * candidate["width_m"], rel=0.01)


def test_the_validator_measures_a_curved_ramp_instead_of_its_bounding_box():
    from backend.app.modules.design.generation.maas.masterplan.ramps import curved_ramp_candidates
    from backend.app.modules.design.generation.maas.masterplan.validation import validate_plan

    data = request(12)
    data["rules"].update(CURVED_RULES)
    rules = data["rules"]
    ramp = curved_ramp_candidates(box(0, 0, 60, 48), LineString([(0, 0), (60, 0)]), Polygon(), rules, 3.3, limit=1)[0]
    basement = shape(data["basement_boundary"])
    result = {"features": [
        {"type": "Feature", "geometry": mapping(basement),
         "properties": {"layer": "basement_boundary", "level": -1}},
        {"type": "Feature", "geometry": mapping(ramp["polygon"]),
         "properties": {"layer": "ramp", "level": -1, "from_level": 0, "to_level": -1,
                        "profile": ramp["profile"], "width_m": ramp["width_m"], "length_m": ramp["length_m"],
                        "layout_type": "curved_arc_with_grade_transitions"}},
        {"type": "Feature", "geometry": mapping(ramp["centerline"]),
         "properties": {"layer": "ramp_centerline", "level": -1, "from_level": 0, "to_level": -1}},
    ], "levels": [{"level": -1, "z_m": -3.3, "provided_spaces": 0}], "metrics": {}}
    checks = {c["id"]: c for c in validate_plan(data, result)["checks"]}
    width = checks["ramp_width:0:-1"]
    radius = checks["ramp_curve_radius:0:-1"]
    assert width["status"] == "passed" and width["measured_width_m"] == pytest.approx(ramp["width_m"], abs=0.01)
    assert radius["status"] == "passed"
    assert radius["measured_inner_radius_m"] == pytest.approx(ramp["inner_radius_m"], abs=0.05)
    assert checks["ramp_profile_length:0:-1"]["status"] == "passed"


def test_a_turn_tighter_than_the_rule_is_refused_by_the_validator():
    from backend.app.modules.design.generation.maas.masterplan.validation import validate_plan

    data = request(12)
    data["rules"].update(CURVED_RULES)
    spine = LineString([(10, 2), (10, 8)] + [(10 + 3*(1 - __import__("math").cos(t/10*__import__("math").pi/2)),
                                             8 + 3*__import__("math").sin(t/10*__import__("math").pi/2))
                                            for t in range(1, 11)])          # a 3 m radius turn
    band = spine.buffer(3.25, cap_style=2, join_style=1, quad_segs=32)
    result = {"features": [
        {"type": "Feature", "geometry": mapping(shape(data["basement_boundary"])),
         "properties": {"layer": "basement_boundary", "level": -1}},
        {"type": "Feature", "geometry": mapping(band),
         "properties": {"layer": "ramp", "level": -1, "from_level": 0, "to_level": -1,
                        "profile": [{"distance_m": 0, "z_m": 0}, {"distance_m": spine.length, "z_m": -3.3}],
                        "width_m": 6.5, "length_m": spine.length,
                        "layout_type": "curved_arc_with_grade_transitions"}},
        {"type": "Feature", "geometry": mapping(spine),
         "properties": {"layer": "ramp_centerline", "level": -1, "from_level": 0, "to_level": -1}},
    ], "levels": [{"level": -1, "z_m": -3.3, "provided_spaces": 0}], "metrics": {}}
    checks = {c["id"]: c for c in validate_plan(data, result)["checks"]}
    assert checks["ramp_curve_radius:0:-1"]["status"] == "failed", checks["ramp_curve_radius:0:-1"]
