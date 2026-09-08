import json

import pytest

from backend.app.modules.llm_planner.contracts import (
    ContractValidationError,
    dump_building_floor_assignments_json,
    dump_program_graph_proposal_json,
    parse_building_floor_assignments_json,
    parse_program_graph_proposal_json,
)


def _assignment_payload() -> dict:
    return {
        "project_id": "tower-a",
        "assignments": [
            {"floor_index": 2, "use_type": "office"},
            {"floor_index": 1, "use_type": "neighborhood_commercial"},
        ],
    }


def _program_payload() -> dict:
    return {
        "project_id": "tower-a",
        "floor_index": 2,
        "use_type": "office",
        "nodes": [
            {
                "node_id": "office",
                "space_type": "office_area",
                "target_area": 80,
                "min_area": 70,
                "max_area": 90,
                "frontage_required": False,
                "min_width": 6,
                "max_aspect_ratio": 2.5,
                "zone": "workplace",
            },
            {
                "node_id": "core",
                "space_type": "core",
                "target_area": 20,
                "min_area": 18,
                "max_area": 22,
                "frontage_required": False,
                "min_width": 3,
                "max_aspect_ratio": 2,
                "zone": "core",
            },
        ],
        "edges": [
            {
                "source": "office",
                "target": "core",
                "relation": "vertical_access",
                "weight": 1,
            }
        ],
    }


def test_floor_assignments_parse_and_dump_deterministically():
    first = parse_building_floor_assignments_json(json.dumps(_assignment_payload()))
    reversed_payload = _assignment_payload()
    reversed_payload["assignments"].reverse()
    second = parse_building_floor_assignments_json(json.dumps(reversed_payload))

    assert [item.floor_index for item in first.assignments] == [1, 2]
    assert first == second
    assert dump_building_floor_assignments_json(first) == (
        '{"assignments":[{"floor_index":1,"use_type":"neighborhood_commercial"},'
        '{"floor_index":2,"use_type":"office"}],"project_id":"tower-a"}'
    )


@pytest.mark.parametrize(
    "payload",
    [
        "{",
        "null",
        '{"project_id":"tower-a","assignments":[],"extra":true}',
        '{"project_id":"","assignments":[]}',
        '{"project_id":"tower-a","assignments":"office"}',
        '{"project_id":"tower-a","assignments":[{"floor_index":true,"use_type":"office"}]}',
    ],
)
def test_floor_assignments_reject_invalid_json_or_shape(payload):
    with pytest.raises(ContractValidationError):
        parse_building_floor_assignments_json(payload)


def test_floor_assignments_reject_unknown_use_type():
    payload = _assignment_payload()
    payload["assignments"][0]["use_type"] = "hotel"

    with pytest.raises(ContractValidationError, match="unsupported use_type"):
        parse_building_floor_assignments_json(json.dumps(payload))


def test_floor_assignments_reject_duplicate_floor():
    payload = _assignment_payload()
    payload["assignments"][1]["floor_index"] = 2

    with pytest.raises(ContractValidationError, match="duplicate floor_index 2"):
        parse_building_floor_assignments_json(json.dumps(payload))


def test_program_graph_proposal_parse_and_dump_deterministically():
    first = parse_program_graph_proposal_json(json.dumps(_program_payload()))
    reversed_payload = _program_payload()
    reversed_payload["nodes"].reverse()
    second = parse_program_graph_proposal_json(json.dumps(reversed_payload))

    assert [node.node_id for node in first.nodes] == ["core", "office"]
    assert first == second
    assert json.loads(dump_program_graph_proposal_json(first)) == {
        "project_id": "tower-a",
        "floor_index": 2,
        "use_type": "office",
        "nodes": [
            {
                "node_id": "core",
                "space_type": "core",
                "target_area": 20.0,
                "min_area": 18.0,
                "max_area": 22.0,
                "frontage_required": False,
                "min_width": 3.0,
                "max_aspect_ratio": 2.0,
                "zone": "core",
            },
            {
                "node_id": "office",
                "space_type": "office_area",
                "target_area": 80.0,
                "min_area": 70.0,
                "max_area": 90.0,
                "frontage_required": False,
                "min_width": 6.0,
                "max_aspect_ratio": 2.5,
                "zone": "workplace",
            },
        ],
        "edges": [
            {
                "source": "office",
                "target": "core",
                "relation": "vertical_access",
                "weight": 1.0,
            }
        ],
    }


def test_program_graph_proposal_rejects_unknown_use_type():
    payload = _program_payload()
    payload["use_type"] = "hotel"

    with pytest.raises(ContractValidationError, match="unsupported use_type"):
        parse_program_graph_proposal_json(json.dumps(payload))


def test_program_graph_proposal_rejects_missing_core():
    payload = _program_payload()
    payload["nodes"] = [payload["nodes"][0]]
    payload["edges"] = []

    with pytest.raises(ContractValidationError, match="exactly one core"):
        parse_program_graph_proposal_json(json.dumps(payload))


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda payload: payload.update(extra=True), "unknown fields"),
        (
            lambda payload: payload["nodes"].append(dict(payload["nodes"][0])),
            "duplicate node_id",
        ),
        (
            lambda payload: payload["nodes"][0].update(target_area=0),
            "finite and positive",
        ),
        (
            lambda payload: payload["nodes"][0].update(min_area=95),
            "min_area must not exceed target_area",
        ),
        (
            lambda payload: payload["edges"][0].update(target="missing"),
            "unknown endpoint",
        ),
    ],
)
def test_program_graph_proposal_rejects_invalid_structure(mutation, message):
    payload = _program_payload()
    mutation(payload)

    with pytest.raises(ContractValidationError, match=message):
        parse_program_graph_proposal_json(json.dumps(payload))
