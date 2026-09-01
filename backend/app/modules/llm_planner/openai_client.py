from __future__ import annotations

import json
import os
from typing import Any

from backend.app.schemas.llm import SUPPORTED_USE_TYPES


FLOOR_ASSIGNMENT_SCHEMA = {
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
                                "enum": sorted(SUPPORTED_USE_TYPES),
                    },
                },
                "required": ["floor_index", "use_type"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["project_id", "assignments"],
    "additionalProperties": False,
}


class OpenAIResponsesPlannerClient:
    def __init__(
        self,
        *,
        model: str | None = None,
        sdk_client: Any | None = None,
    ) -> None:
        self.provider = "openai"
        self.model = model or os.getenv("PLAN_LLM_MODEL", "gpt-5.6")
        self.last_response_id: str | None = None
        self.last_response_model: str | None = None
        if sdk_client is None:
            from openai import OpenAI

            sdk_client = OpenAI()
        self._client = sdk_client

    def complete_json(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
    ) -> str:
        self.last_response_id = None
        self.last_response_model = None
        response = self._client.responses.create(
            model=self.model,
            store=False,
            instructions=system_prompt,
            input=json.dumps(
                user_payload,
                ensure_ascii=True,
                allow_nan=False,
                sort_keys=True,
            ),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "building_floor_assignments",
                    "strict": True,
                    "schema": FLOOR_ASSIGNMENT_SCHEMA,
                }
            },
        )
        response_id = getattr(response, "id", None)
        self.last_response_id = response_id if isinstance(response_id, str) else None
        self.last_response_model = self.model
        output_text = response.output_text
        if not isinstance(output_text, str) or not output_text.strip():
            raise RuntimeError("OpenAI returned an empty structured response")
        return output_text
