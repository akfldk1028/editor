"""Mass feedback makes parking demand reviewable without redesigning the mass."""
import copy
import sys

import pytest



def feedback(request, result):
    from backend.app.modules.design.generation.maas.masterplan.feedback import build_mass_feedback

    return build_mass_feedback(request, result)


def fixture(*, required=50, provided=50, ground=8, basement=(35, 7),
            blocking=(), ratio=None, law_snapshot=True):
    law = {"status": "resolved", "required_spaces": required, "source_task_ids": ["fixture-count"]}
    rules = {"status": "resolved"}
    if law_snapshot:
        rules["source_snapshot"] = {"source": "fixture-rule", "effective_date": "2026-07-27"}
    request = {"footprint": {"type": "Polygon", "coordinates": [[[0, 0], [20, 0], [20, 20], [0, 20], [0, 0]]]},
               "law": law, "options": {"max_basement_levels": 2}}
    if ratio is not None:
        request["options"]["parking_efficiency_ratio"] = ratio
    levels = [{"level": 0, "provided_spaces": ground}]
    for depth, count in enumerate(basement, 1):
        levels.append({"level": -depth, "provided_spaces": count,
                       "plate_area_m2": 1000.0 if depth == 1 else 900.0,
                       "plate_area_per_stall_m2": round((1000 if depth == 1 else 900) / count, 2) if count else None,
                       "over_module_ideal_basis": "excavated_plate"})
    result = {"status": "needs_revision" if blocking else "resolved", "blocking": list(blocking),
              "validation": {"geometry_status": "failed" if blocking else "passed", "checks": []},
              "metrics": {"required_parking_stalls": required, "planned_parking_stalls": required,
                          "provided_parking_stalls": provided, "module_ideal_m2": 20.0,
                          "building_footprint_m2": 400.0, "basement_levels": len(basement)},
              "levels": levels, "provenance": {"law": law, "rules": rules}}
    return request, result


def test_explicit_planned_target_survives_unknown_law_without_legal_claim():
    request, result = fixture(required=None, provided=9, ground=9, basement=())
    result['metrics']['planned_parking_stalls'] = 50
    out = feedback(request, result)
    assert out['status'] == 'needs_evidence'
    assert out['demand']['planned_stalls'] == 50
    assert out['demand']['planning_target_stalls'] == 50
    assert out['demand']['shortfall_stalls'] == 41
    assert out['demand']['legal_shortfall_stalls'] is None
    assert out['demand']['required_stalls'] is None


@pytest.mark.parametrize('depth', [6, 100, -1, 1.5, True])
def test_feedback_rejects_depth_outside_planner_contract(depth):
    request, result = fixture()
    request['options']['max_basement_levels'] = depth
    with pytest.raises(ValueError, match='basement'):
        feedback(request, result)


def test_feedback_rejects_observed_level_outside_planner_contract():
    request, result = fixture()
    result['levels'].append({'level': -100, 'provided_spaces': 0})
    with pytest.raises(ValueError, match='basement'):
        feedback(request, result)


def test_no_authoritative_count_stays_evidence_request_not_mass_change():
    request, result = fixture(required=None, provided=0, ground=0, basement=(), law_snapshot=False)
    request["law"]["status"] = "needs_evidence"
    result["metrics"]["module_ideal_m2"] = None
    out = feedback(request, result)
    assert out["status"] == "needs_evidence"
    assert out["demand"]["shortfall_stalls"] is None
    assert out["area_basis"]["ideal_lower_bound_m2"] is None
    assert out["area_basis"]["workable_area_budget_m2"] is None
    assert [action["id"] for action in out["actions"]] == ["obtain_law_count_evidence"]
    assert out["mass_context"]["authored_footprint"] is True


def test_no_ramp_shortfall_requests_ramp_and_mass_review_without_claiming_area_fit():
    request, result = fixture(required=50, provided=8, ground=8, basement=(),
                              blocking=("no straight or curved ramp fits the supplied site/frontage and obstructions",
                                        "parking shortfall: 8 of 50 stalls placed"))
    before = copy.deepcopy(request)
    out = feedback(request, result)
    assert request == before
    assert out["status"] == "review_required"
    assert out["demand"]["shortfall_stalls"] == 42
    assert out["demand"]["basement_required_min_stalls"] == 42
    assert out["area_basis"]["ideal_lower_bound_m2"] == 840.0
    assert out["area_basis"]["workable_area_budget_m2"] is None
    assert out["levels"][1]["level"] == -1
    assert out["levels"][1]["proposed_required_stalls"] == 42
    assert out["levels"][1]["proposed_net_parking_area_m2"] is None
    assert {a["id"] for a in out["actions"]} >= {"investigate_ramp_fit", "review_massing_for_shortfall"}
    assert all(a["review_required"] for a in out["actions"])


def test_explicit_efficiency_assumption_yields_reviewable_plate_reduction():
    request, result = fixture(ratio=1.5, blocking=("level -2 carries 7 stalls at 128.57 m2 each, thin",))
    out = feedback(request, result)
    b2 = next(level for level in out["levels"] if level["level"] == -2)
    assert out["area_basis"]["workable_area_budget_m2"] == 1260.0
    assert out["area_basis"]["assumption_source"] == "request.options.parking_efficiency_ratio"
    assert b2["proposed_required_stalls"] == 7
    assert b2["proposed_net_parking_area_m2"] == 210.0
    assert b2["area_reduction_vs_actual_m2"] == 690.0
    assert any(a["id"] == "review_inefficient_basement_plate" for a in out["actions"])
    assert out["mass_context"]["proposed_footprint_geometry"] is None


def test_count_reduction_frees_deepest_level_first_as_explicit_design_proposal():
    request, result = fixture(required=50, provided=59, ground=8, basement=(42, 9), ratio=1.5)
    out = feedback(request, result)
    by_level = {entry["level"]: entry for entry in out["levels"]}
    assert by_level[-1]["proposed_required_stalls"] == 42
    assert by_level[-2]["proposed_required_stalls"] == 0
    assert sum(x["proposed_required_stalls"] for x in out["levels"]) == 50
    assert any(a["id"] == "review_eliminating_deep_level" for a in out["actions"])


def test_missing_snapshot_keeps_geometry_finding_preliminary():
    request, result = fixture(provided=8, ground=8, basement=(), law_snapshot=False,
                              blocking=("no straight or curved ramp fits",))
    out = feedback(request, result)
    assert out["status"] == "needs_evidence"
    assert out["provenance"]["law_snapshot_status"] == "missing"
    action = next(a for a in out["actions"] if a["id"] == "investigate_ramp_fit")
    assert action["evidence_status"] == "preliminary_geometry"


def test_invalid_efficiency_ratio_is_rejected_not_clamped():
    request, result = fixture(ratio=0.9)
    with pytest.raises(ValueError, match="parking_efficiency_ratio"):
        feedback(request, result)
