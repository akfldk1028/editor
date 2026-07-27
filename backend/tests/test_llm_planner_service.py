import json

import pytest

from backend.app.modules.llm_planner.contracts import ContractValidationError
from backend.app.modules.llm_planner.service import (
    plan_floor_assignments,
    run_llm_building_generation,
)
from backend.app.schemas.mass import MassInput


class RecordingPlannerClient:
    def __init__(self, response: str):
        self.response = response
        self.calls: list[dict] = []

    def complete_json(self, *, system_prompt: str, user_payload: dict) -> str:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_payload": user_payload,
            }
        )
        return self.response


def _sample_mass() -> MassInput:
    return MassInput(
        project_id="llm-building",
        floors=3,
        footprint_polygon=[(0, 0), (24, 0), (24, 12), (0, 12)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"neighborhood_commercial": 1 / 3, "office": 2 / 3},
    )


def _valid_response(**overrides) -> str:
    payload = {
        "project_id": "llm-building",
        "assignments": [
            {"floor_index": 1, "use_type": "neighborhood_commercial"},
            {"floor_index": 2, "use_type": "office"},
            {"floor_index": 3, "use_type": "office"},
        ],
    }
    payload.update(overrides)
    return json.dumps(payload)


def test_plan_floor_assignments_parses_valid_structured_response():
    client = RecordingPlannerClient(_valid_response())

    plan = plan_floor_assignments(_sample_mass(), client)

    assert plan.project_id == "llm-building"
    assert [
        (assignment.floor_index, assignment.use_type)
        for assignment in plan.assignments
    ] == [
        (1, "neighborhood_commercial"),
        (2, "office"),
        (3, "office"),
    ]


def test_run_llm_building_generation_uses_structured_assignments():
    client = RecordingPlannerClient(_valid_response())

    result = run_llm_building_generation(_sample_mass(), client)

    assert result.assignment_source == "structured"
    assert [
        floor.program.use_type for floor in result.floor_results
    ] == ["neighborhood_commercial", "office", "office"]
    assert result.accepted


def test_plan_floor_assignments_rejects_invalid_json():
    client = RecordingPlannerClient("{")

    with pytest.raises(ContractValidationError, match="invalid JSON"):
        plan_floor_assignments(_sample_mass(), client)


def test_plan_floor_assignments_rejects_project_mismatch():
    client = RecordingPlannerClient(_valid_response(project_id="other-project"))

    with pytest.raises(ContractValidationError, match="project_id"):
        plan_floor_assignments(_sample_mass(), client)


def test_plan_floor_assignments_rejects_missing_floor():
    payload = json.loads(_valid_response())
    payload["assignments"].pop()
    client = RecordingPlannerClient(json.dumps(payload))

    with pytest.raises(ContractValidationError, match="floor"):
        plan_floor_assignments(_sample_mass(), client)


def test_plan_floor_assignments_rejects_use_mix_count_violation():
    client = RecordingPlannerClient(
        _valid_response(
            assignments=[
                {"floor_index": 1, "use_type": "office"},
                {"floor_index": 2, "use_type": "office"},
                {"floor_index": 3, "use_type": "office"},
            ]
        )
    )

    with pytest.raises(ContractValidationError, match="use_mix"):
        plan_floor_assignments(_sample_mass(), client)


def test_plan_floor_assignments_requires_commercial_below_office():
    client = RecordingPlannerClient(
        _valid_response(
            assignments=[
                {"floor_index": 1, "use_type": "office"},
                {"floor_index": 2, "use_type": "neighborhood_commercial"},
                {"floor_index": 3, "use_type": "office"},
            ]
        )
    )

    with pytest.raises(ContractValidationError, match="lower floors"):
        plan_floor_assignments(_sample_mass(), client)


def test_plan_floor_assignments_sends_complete_mass_context():
    mass = _sample_mass()
    client = RecordingPlannerClient(_valid_response())

    plan_floor_assignments(mass, client)

    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["system_prompt"]
    assert call["user_payload"] == {
        "project_id": mass.project_id,
        "floors": mass.floors,
        "footprint_polygon": mass.footprint_polygon,
        "site_edges": mass.site_edges,
        "access_candidates": mass.access_candidates,
        "use_mix": mass.use_mix,
    }
