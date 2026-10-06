"""Compact excavation proposals preserve every declared below-grade object."""
import sys

import pytest
from shapely.geometry import box, mapping
from backend.app.modules.design.generation.maas.masterplan.compact_slab import compact_slab_candidate


def feat(layer, geom, level=-1):
    return {"type": "Feature", "geometry": mapping(geom), "properties": {"layer": layer, "level": level}}


def test_compact_alternative_preserves_programme_and_ramp_without_full_plate():
    features = [feat("basement_boundary", box(0, 0, 60, 50)),
        feat("parking_stall", box(10, 10, 15, 15)),
        feat("parking_aisle", box(10, 15, 30, 21)),
        feat("ramp", box(25, 21, 31, 41)),
        feat("building_core", box(16, 23, 22, 28)),
        feat("basement_room", box(31, 15, 38, 23)),
        feat("building_footprint", box(0, 0, 60, 50), 0)]
    result = compact_slab_candidate(features, level=-1, envelope=box(0, 0, 60, 50))
    assert result["polygon"].area < 1800
    assert result["saved_area_m2"] > 1200
    from shapely.geometry import shape
    assert all(result["polygon"].covers(shape(f["geometry"])) for f in features[1:-1])
    assert "wall_clearance_not_declared" in result["pending_reviews"]
    assert result["status"] == "concept_candidate"


def test_explicit_clearance_is_reserved_not_guessed():
    features = [feat("parking_aisle", box(5, 5, 15, 15))]
    result = compact_slab_candidate(features, level=-1, envelope=box(0, 0, 20, 20), wall_clearance_m=1)
    assert result["polygon"].covers(box(4, 4, 16, 16))
    assert "wall_clearance_not_declared" not in result["pending_reviews"]


def test_nonconvex_envelope_does_not_clip_away_required_geometry():
    envelope = box(0, 0, 10, 30).union(box(0, 0, 30, 10))
    features = [feat("parking_aisle", box(1, 20, 9, 29)), feat("basement_room", box(20, 1, 29, 9))]
    result = compact_slab_candidate(features, level=-1, envelope=envelope)
    assert result["status"] == "no_candidate"
    assert result["polygon"] is None
    assert result["reason"] == "convex slab exceeds excavation envelope"


def test_concave_connected_slab_can_follow_envelope_without_cutting_programme():
    envelope=box(0,0,10,30).union(box(0,0,30,10))
    drive=box(1,1,9,29).union(box(1,1,29,9))
    result=compact_slab_candidate([feat('basement_boundary',envelope),feat('parking_aisle',drive)],
                                  level=-1,envelope=envelope)
    assert result['status']=='concept_candidate'
    assert envelope.covers(result['polygon']) and result['polygon'].covers(drive)


def test_other_level_geometry_is_not_accidentally_used():
    features = [feat("parking_aisle", box(5, 5, 15, 15), -2)]
    assert compact_slab_candidate(features, level=-1, envelope=box(0, 0, 20, 20))["status"] == "no_candidate"


@pytest.mark.parametrize("clearance", [-1, float("nan"), float("inf")])
def test_invalid_clearance_is_rejected(clearance):
    with pytest.raises(ValueError):
        compact_slab_candidate([], level=-1, envelope=box(0, 0, 20, 20), wall_clearance_m=clearance)


def test_planner_keeps_original_and_validates_compact_alternative(monkeypatch):
    import backend.app.modules.design.generation.maas.masterplan.planner as planner
    from test_masterplan_engine import request
    monkeypatch.setattr(planner, "row_candidates", lambda *a, **k: [])
    ramps = planner.ramp_candidates
    monkeypatch.setattr(planner, "ramp_candidates", lambda *a, **k: ramps(*a, **k)[:1])
    monkeypatch.setattr(planner, "curved_ramp_candidates", lambda *a, **k: [])
    # One ramp and ONE plate, the declared host (slab_envelopes returns it last): the compact
    # proposal is then measured against the plate it was derived from. Demand-sized plates came
    # later and can dig less than any compaction of the full host, which is a different question.
    slabs = planner.slab_envelopes
    monkeypatch.setattr(planner, "slab_envelopes", lambda *a, **k: slabs(*a, **k)[-1:])
    data = request(2, "basement")
    data["law"]["required_accessible_spaces"] = 0
    data["options"].update(target_surface_stalls=0, max_basement_levels=1)
    result = planner.plan_site(data)
    compact = [c for c in result["alternatives"] if c.get("compact_slab")]
    original = [c for c in result["alternatives"] if not c.get("compact_slab")]
    assert compact and original
    assert result["provenance"]["compact_slab"]["saved_area_m2"] > 0
    assert result["metrics"]["original_excavation_m2"] > result["metrics"]["excavation_m2"]
    assert "wall_clearance_not_declared" in result["blocking"]
    assert result["status"] != "resolved"
    compact_check = next(c for c in result["validation"]["checks"]
                         if c["id"] == "compact_slab_preserves_programme:-1")
    assert compact_check["status"] == "passed"
    import copy
    from backend.app.modules.design.generation.maas.masterplan.validation import validate_plan
    tampered = copy.deepcopy(result)
    slab = next(f for f in tampered["features"] if f["properties"].get("compact_candidate"))
    slab["geometry"] = mapping(box(0, 0, 1, 1))
    assert next(c for c in validate_plan(data, tampered)["checks"]
                if c["id"] == "compact_slab_preserves_programme:-1")["status"] == "failed"
    for c in compact:
        assert c["geometry_status"] in {"passed", "failed"}
    data["options"]["compact_basement_search"] = False
    ordinary = planner.plan_site(data)
    assert not any(c.get("compact_slab") for c in ordinary["alternatives"])
