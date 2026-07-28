import json

import pytest

from backend.app.modules.llm_planner.openai_client import (
    OpenAIResponsesPlannerClient,
)


class FakeResponses:
    def __init__(self, output_text: str, response_id: str = "resp_test"):
        self.output_text = output_text
        self.response_id = response_id
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return type(
            "Response",
            (),
            {"output_text": self.output_text, "id": self.response_id},
        )()


class FakeOpenAI:
    def __init__(self, output_text: str):
        self.responses = FakeResponses(output_text)


def test_openai_planner_client_uses_responses_strict_json_schema():
    sdk = FakeOpenAI(
        '{"project_id":"sample","assignments":'
        '[{"floor_index":1,"use_type":"office"}]}'
    )
    client = OpenAIResponsesPlannerClient(
        model="gpt-test",
        sdk_client=sdk,
    )
    payload = {
        "project_id": "sample",
        "floors": 1,
        "footprint_polygon": [(0, 0), (10, 0), (10, 10), (0, 10)],
        "site_edges": [],
        "access_candidates": [],
        "use_mix": {"office": 1.0},
    }

    result = client.complete_json(
        system_prompt="assign floors",
        user_payload=payload,
    )

    assert json.loads(result)["project_id"] == "sample"
    assert client.provider == "openai"
    assert client.last_response_id == "resp_test"
    assert client.last_response_model == "gpt-test"
    assert len(sdk.responses.calls) == 1
    request = sdk.responses.calls[0]
    assert request["model"] == "gpt-test"
    assert request["store"] is False
    assert request["instructions"] == "assign floors"
    assert json.loads(request["input"]) == json.loads(json.dumps(payload))
    assert request["text"]["format"] == {
        "type": "json_schema",
        "name": "building_floor_assignments",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "assignments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "floor_index": {"type": "integer", "minimum": 1},
                            "use_type": {
                                "type": "string",
                                "enum": [
                                    "neighborhood_commercial",
                                    "office",
                                ],
                            },
                        },
                        "required": ["floor_index", "use_type"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["project_id", "assignments"],
            "additionalProperties": False,
        },
    }


def test_openai_planner_client_rejects_empty_model_output():
    client = OpenAIResponsesPlannerClient(
        model="gpt-test",
        sdk_client=FakeOpenAI(""),
    )

    with pytest.raises(RuntimeError, match="empty"):
        client.complete_json(system_prompt="assign", user_payload={})


def test_openai_planner_client_reads_model_from_environment(monkeypatch):
    monkeypatch.setenv("PLAN_LLM_MODEL", "gpt-env")

    client = OpenAIResponsesPlannerClient(sdk_client=FakeOpenAI("{}"))

    assert client.model == "gpt-env"
