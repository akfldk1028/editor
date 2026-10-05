"""Independent geometry expectations for the actual ARR planning engine."""
import copy
import sys
from pathlib import Path

import pytest
from shapely.geometry import LineString, Polygon, box, mapping, shape



def engine():
    try:
        from backend.app.modules.design.generation.maas.masterplan.planner import plan_site
        return plan_site
    except ImportError as exc:
        pytest.fail(f"The site/basement planning engine is missing: {exc}")


def request(required=12, strategy="basement", basement=None):
    # `basement` declares the excavated slab.  The default is the whole parcel, which is not a
    # realistic excavation - tests that measure a basement AGAINST its slab pass a real one.
    return {
        "pnu": "1168010100106770000", "crs": "EPSG:32652",
        "site": mapping(box(0, 0, 60, 48)),
        "buildable": mapping(box(2, 2, 58, 46)),
        "footprint": mapping(box(18, 10, 48, 36)),
        "core": mapping(box(29, 20, 35, 26)),
        "columns": [],
        "frontage": mapping(LineString([(0, 0), (60, 0)])),
        "basement_boundary": mapping(basement or box(0, 0, 60, 48)),
        "law": {
            "status": "resolved", "bcr_pct": 60.0, "required_spaces": required,
            "required_accessible_spaces": 1, "max_spaces": None,
            "source_task_ids": ["fixture-law"], "blocking": [],
        },
        "rules": {
            "status": "resolved", "source": "test fixture, not live law",
            "stall_width_m": 2.5, "stall_length_m": 5.0,
            "accessible_width_m": 3.3, "accessible_length_m": 5.0,
            "aisle_width_m": 6.0, "ramp_width_m": 6.0,
            "ramp_max_slope": 0.15, "transition_length_m": 3.0,
            "transition_slope": 0.075, "min_headroom_m": 2.3,
        },
        "options": {"parking_strategy": strategy, "max_basement_levels": 2,
                    "basement_floor_height_m": 3.3, "slab_depth_m": 0.3},
        "evidence": {"buildable": "fixture", "frontage": "fixture", "core": "fixture",
                     "columns": "fixture", "basement_boundary": "fixture"},
    }


def test_basement_has_real_ramp_profile_and_disjoint_parking_geometry():
    result = engine()(request())
    feats = result["features"]
    ramps = [f for f in feats if f["properties"]["layer"] == "ramp"]
    stalls = [f for f in feats if f["properties"]["layer"] == "parking_stall"]
    assert ramps, result
    assert len(stalls) == 12, result.get("blocking")
    assert {f["properties"]["level"] for f in stalls} == {-1}
    for ramp in ramps:
        profile = ramp["properties"]["profile"]
        assert profile[0]["z_m"] == pytest.approx(0)
        assert profile[-1]["z_m"] == pytest.approx(-3.3)
        for a, b in zip(profile, profile[1:]):
            assert abs(b["z_m"]-a["z_m"])/(b["distance_m"]-a["distance_m"]) <= .15 + 1e-8
        for stall in stalls:
            assert shape(ramp["geometry"]).intersection(shape(stall["geometry"])).area < 1e-7
    assert result["validation"]["geometry_status"] == "passed", result["validation"]


def test_insufficient_site_never_reports_success_or_changes_to_surface():
    data = request(12)
    data.update(site=mapping(box(0, 0, 12, 12)), buildable=mapping(box(1, 1, 11, 11)),
                footprint=mapping(box(3, 3, 9, 9)), core=mapping(box(4, 4, 6, 6)),
                frontage=mapping(LineString([(0, 0), (12, 0)])),
                basement_boundary=mapping(box(0, 0, 12, 12)))
    result = engine()(data)
    assert result["status"] == "needs_revision"
    assert result["metrics"]["provided_parking_stalls"] < 12
    assert any("ramp" in str(x) for x in result["blocking"])


def test_missing_law_does_not_become_eight_stalls_or_resolved():
    data = request()
    data["law"] = {"status": "needs_evidence", "blocking": ["law unavailable"]}
    result = engine()(data)
    assert result["status"] == "needs_evidence"
    assert result["metrics"]["required_parking_stalls"] is None
    assert any("law" in str(x) for x in result["blocking"])


def test_existing_mass_is_not_silently_moved_or_clipped():
    data = request()
    data["footprint"] = mapping(box(50, 20, 70, 40))
    result = engine()(data)
    assert result["status"] == "needs_revision"
    building = next(f for f in result["features"] if f["properties"]["layer"] == "building_footprint")
    assert shape(building["geometry"]).equals(box(50, 20, 70, 40))
    assert any("footprint" in str(x) for x in result["blocking"])


def test_validator_rejects_tampered_stall_and_ramp():
    result = engine()(request())
    from backend.app.modules.design.generation.maas.masterplan.validation import validate_plan
    damaged = copy.deepcopy(result)
    stall = next(f for f in damaged["features"] if f["properties"]["layer"] == "parking_stall")
    stall["geometry"] = mapping(box(70, 70, 72.5, 75))
    ramp = next(f for f in damaged["features"] if f["properties"]["layer"] == "ramp")
    ramp["properties"]["profile"][-1]["z_m"] = -30
    validation = validate_plan(request(), damaged)
    assert validation["geometry_status"] == "failed"
    assert any(c["status"] == "failed" and "containment" in c["id"] for c in validation["checks"])
    assert any(c["status"] == "failed" and "ramp" in c["id"] for c in validation["checks"])


def test_concave_generated_footprint_is_inside_and_respects_target():
    from scripts import layout_synthesizer
    parcel = Polygon([(0, 0), (20, 0), (20, 20), (17, 20), (17, 3), (3, 3), (3, 20), (0, 20)])
    footprint = layout_synthesizer.compute_oriented_mass_footprint(parcel, 97.2)
    assert parcel.covers(footprint)
    assert footprint.area <= 97.2 + 1e-7


def test_small_requested_footprint_is_not_enlarged():
    from scripts import layout_synthesizer
    footprint = layout_synthesizer.compute_oriented_mass_footprint(box(0, 0, 20, 25), 5)
    assert 0 < footprint.area <= 5 + 1e-7


def test_multilevel_plan_reserves_ramps_and_counts_each_floor_once():
    data = request(150)
    result = engine()(data)
    assert result["metrics"]["basement_levels"] == 2
    assert result["metrics"]["provided_parking_stalls"] == 150
    ramps = [f for f in result["features"] if f["properties"]["layer"] == "ramp"]
    assert {(r["properties"]["from_level"],r["properties"]["to_level"]) for r in ramps} == {(0,-1),(-1,-2)}
    assert result["validation"]["geometry_status"] == "passed", result["validation"]


def test_validator_uses_source_obstacles_even_if_drawn_core_is_deleted():
    data = request()
    result = engine()(data)
    from backend.app.modules.design.generation.maas.masterplan.validation import validate_plan
    result["features"] = [f for f in result["features"] if f["properties"]["layer"] != "building_core"]
    stall = next(f for f in result["features"] if f["properties"]["layer"] == "parking_stall")
    stall["geometry"] = mapping(box(29,20,31.5,25))
    checks = validate_plan(data,result)["checks"]
    assert any(c["id"].startswith("stall_obstructions") and c["status"] == "failed" for c in checks)


def test_generated_footprint_respects_the_rounded_law_capacity():
    # Lawagent reports ground_capacity_m2 rounded to 3 decimals; site x BCR is
    # slightly larger. The generated footprint must not exceed the stated cap.
    data = request()
    data.pop("footprint")
    data["site"] = mapping(box(0, 0, 60.001, 48.001))            # area 2880.096...
    data["law"]["ground_capacity_m2"] = 1728.0                    # below 60% x area = 1728.058
    result = engine()(data)
    building = next(f for f in result["features"] if f["properties"]["layer"] == "building_footprint")
    assert building["properties"]["area_m2"] <= 1728.0 + 1e-6
    assert not any(c["id"] == "footprint_area" and c["status"] == "failed" for c in result["validation"]["checks"])


def test_mixed_surface_and_basement_each_reach_the_road():
    # A surface lot and a ramp departure need not share an aisle; each ground
    # drive component must touch the road. Before this, every mixed scheme on a
    # real parcel failed drive_connected:0 although both reached the frontage.
    data = request(150, strategy="mixed")   # more than the surface alone can hold
    result = engine()(data)
    assert result["metrics"]["provided_parking_stalls"] == 150, result["blocking"]
    assert result["metrics"]["basement_levels"] >= 1
    assert result["levels"][0]["provided_spaces"] > 0
    assert result["validation"]["geometry_status"] == "passed", [c for c in result["validation"]["checks"] if c["status"] == "failed"]
    ground_drive = [c for c in result["validation"]["checks"] if c["id"] == "drive_connected:0"][0]
    assert ground_drive["components"] >= 1


def test_generated_footprint_sits_on_the_declared_front_edge():
    # Practice sits a public building against its highest-hierarchy road with the
    # building line's open space in front; the generated proposal must do the same.
    data = request(12, strategy="surface")
    data.pop("footprint"); data["core"] = None
    data["front_frontage"] = mapping(LineString([(2, 46), (58, 46)]))   # north edge of the buildable box(2,2,58,46)
    result = engine()(data)
    fp = shape(next(f for f in result["features"] if f["properties"]["layer"] == "building_footprint")["geometry"])
    assert fp.bounds[3] == pytest.approx(46.0, abs=1e-6), fp.bounds       # flush with the front limit
    assert fp.area == pytest.approx(min(2880 * 0.6, 1728.0), rel=1e-3)
    assert fp.minimum_rotated_rectangle.symmetric_difference(fp).area < 1e-6    # a rectangle parallel to the edge
    assert "front road hierarchy unverified" not in " ".join(result["blocking"])
    # no surface stall sits in the front strip between the building and its road
    front = LineString([(2, 46), (58, 46)])
    for f in result["features"]:
        if f["properties"]["layer"] == "parking_stall":
            assert shape(f["geometry"]).distance(front) >= 8.0 - 1e-6, f["properties"]


def test_basement_strategy_keeps_the_ground_clear_and_reports_module_efficiency():
    # A basement-only plan keeps the ground for the entrance aisle and the ramp, and the plan that
    # wins is the one that carries its cars in the least area: area per stall against the ideal
    # double-loaded module is a first-class metric, and no level may be more than twice the ideal.
    result = engine()(request(40, strategy="basement"))
    metrics = result["metrics"]
    assert metrics["provided_parking_stalls"] == 40
    assert result["validation"]["geometry_status"] == "passed"
    assert metrics["module_ideal_m2"] == pytest.approx(20.0)          # 2.5 * (2*5.0 + 6.0) / 2
    assert metrics["area_per_stall_m2"] is not None
    # This fixture declares the excavation as the whole parcel, so the plate measure means nothing
    # here; the rows themselves must still be tight.  The slab measure is tested below on a fixture
    # that declares a real slab.
    for level in result["levels"]:
        if level.get("area_per_stall_m2") is not None:
            assert level["area_per_stall_m2"] / metrics["module_ideal_m2"] <= 2.0, level
    assert not any(f["properties"]["layer"] == "parking_stall" and f["properties"].get("level", 0) == 0 for f in result["features"])
    fallback = [a for a in result["alternatives"] if a["ramp_orientation"] == "parallel_to_edge" and a["provided_spaces"] == 40]
    assert fallback and any(a["geometry_status"] == "passed" for a in fallback), result["alternatives"]
    assert metrics["excavation_m2"] > 0 and metrics["excavation_over_footprint"] is not None


REAL_SLAB = box(14, 6, 52, 40)          # 38 x 34 m: the plate plus its ramp, 2.1 modules deep


def test_a_basement_is_measured_against_the_slab_it_digs_not_the_rows_it_draws():
    # Dividing by the drawn rows flatters a level that leaves most of its plate empty: a 1,270 m2
    # slab holding 20 cars reports 23.6 m2/stall that way and 63.5 by the slab.  Practice ALT1 runs
    # at 30.3 m2/stall by the slab, and the published planning constant is 30.2 (Kavanagh, The
    # Parking Professional, IPMI 2015).  Below grade the slab is the honest denominator, because the
    # slab is what was paid for; at grade nothing is excavated, so the drawn area stands.
    result = engine()(request(40, strategy="basement", basement=REAL_SLAB))
    below = [lv for lv in result["levels"] if lv["level"] < 0 and lv.get("provided_spaces")]
    assert below, result["levels"]
    for level in below:
        assert level["over_module_ideal_basis"] == "excavated_plate", level
        assert level["plate_area_per_stall_m2"] >= level["area_per_stall_m2"], level


def test_tiling_the_plate_beats_filling_one_band_of_it():
    # A 38 x 34 m plate is 2.1 parking modules deep (16.0 m each).  Filling one band and leaving the
    # rest of the excavation empty is the categorical loss the functional-design canon names
    # (CCDC: "overall width shall be a multiple of the bay width").  The comparison is the contract:
    # against the SAME slab, tiling must not need more levels or more area per stall than one band.
    def run(field):
        data = request(40, strategy="basement", basement=REAL_SLAB)
        data["options"]["parking_field"] = field
        out = engine()(data)
        below = [lv for lv in out["levels"] if lv["level"] < 0 and lv.get("provided_spaces")]
        worst = max((lv["plate_area_per_stall_m2"] for lv in below), default=None)
        return out["metrics"]["provided_parking_stalls"], out["metrics"]["basement_levels"], worst

    single_stalls, single_levels, single_worst = run("single")
    tiled_stalls, tiled_levels, tiled_worst = run("auto")
    assert tiled_stalls >= single_stalls
    assert tiled_levels <= single_levels, (tiled_levels, single_levels)
    if single_worst is not None and tiled_worst is not None:
        assert tiled_worst <= single_worst + 1e-6, (tiled_worst, single_worst)


def test_every_basement_level_says_whether_its_aisle_graph_closes():
    # Whether a driver who misses a space can come round again is a property of the design, so it
    # is reported for EVERY basement level rather than only when a loop was asked for - gating the
    # certificate on `parking_field == 'ring'` made it audit the very choice that produced it, and
    # a dead-end comb passed with zero failures. It stays a MEASUREMENT: 주차장법 시행규칙 제6조·
    # 제11조 carry no 회차 clause (임재문·오세경·김회경, 한국산학기술학회논문지 15(12):7403-7415,
    # 2014), so the binding text is IStructE 3.2.6/4.4 and the verdict is a reviewer's.
    result = engine()(request(40, strategy="basement", basement=REAL_SLAB))
    aisles = [f["properties"] for f in result["features"] if f["properties"]["layer"] == "parking_aisle"]
    assert aisles
    levels = {a.get("level") for a in aisles if (a.get("level") or 0) < 0}
    certs = [c for c in result["validation"]["checks"] if c["id"].startswith("closed_aisle_loop:")]
    assert {int(c["id"].split(":")[1]) for c in certs} >= levels, (certs, levels)
    assert all(c["status"] == "measured" and "closed" in c for c in certs), certs
    # where the tiled packer won, the grammar travels with the feature so a drawing can name it
    for a in (x for x in aisles if x.get("bands")):
        assert a["bands"] >= 1 and a["cross_aisles"] >= 0
        assert isinstance(a["dead_end_stalls"], int)


def test_rotated_site_still_packs_stalls():
    # A real parcel sits at an angle in its UTM frame. Before the principal-angle
    # candidates, the spine box never fit a 7-degree site and zero stalls came back.
    from shapely.affinity import rotate
    data = request(12)
    for key in ("site", "buildable", "footprint", "core", "basement_boundary"):
        data[key] = mapping(rotate(shape(data[key]), 7, origin=(0, 0)))
    data["frontage"] = mapping(rotate(LineString([(0, 0), (60, 0)]), 7, origin=(0, 0)))
    result = engine()(data)
    assert result["metrics"]["provided_parking_stalls"] == 12, result["blocking"]
    assert result["validation"]["geometry_status"] == "passed", result["validation"]


def test_validator_rejects_a_falsified_ramp_profile_length():
    data = request()
    result = engine()(data)
    from backend.app.modules.design.generation.maas.masterplan.validation import validate_plan
    ramp = next(f for f in result["features"] if f["properties"]["layer"] == "ramp")
    for p in ramp["properties"]["profile"]:
        p["distance_m"] *= 2
    checks = validate_plan(data,result)["checks"]
    assert any("profile_length" in c["id"] and c["status"] == "failed" for c in checks)
