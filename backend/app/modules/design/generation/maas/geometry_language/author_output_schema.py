"""Strict provider-output schema for agent-authored geometry AST nodes.

The production parser owns the final contract check.  This module mirrors the
same operator/parameter vocabulary at generation time so a provider cannot
spend a batch on parameter names that the parser must reject.
"""

from __future__ import annotations

from typing import Any

from backend.app.modules.design.generation.maas.geometry_language.ast import OPERATORS_BY_KIND
from backend.app.modules.design.generation.maas.geometry_language.author_parameter_contract import author_parameter_value_contract
from backend.app.modules.design.generation.maas.geometry_language.mutation import OPERATOR_PARAMETER_CONTRACTS


_REQUIRED_PARAMETER_COUNTS = {
    "bound_surfaces": 1,
    "book_base_volume": 2,
    "box": 4,
    "carve_void": 1,
    "courtyard": 1,
    "cut_corner": 2,
    "lift": 1,
    "matrix4": 1,
    "notch": 1,
}


def schema_value_types(contract_type: str) -> list[str]:
    """The `value_type` values the schema accepts for one catalogue contract kind.

    The catalogue speaks in contract kinds - `literal`, `structured_literal`,
    `numeric_vector` - and the schema and importer in value types. This is the
    one translation both the schema and the author's prompt read, so the word
    the author sees is the word the schema will check. Before it was shared,
    the prompt printed the raw kind and an author wrote `value_type: literal`
    into 110 programs.
    """

    return {
        "boolean": ["boolean"],
        "number": ["number"],
        "numeric_vector": ["vector"],
        "string": ["string"],
        "structured_literal": ["structured_json"],
        "matrix4": ["matrix4"],
    }.get(
        str(contract_type or "literal"),
        ["number", "string", "boolean", "vector", "structured_json"],
    )


def _parameter_variant(operator: str, name: str) -> dict[str, Any]:
    contract = author_parameter_value_contract(operator, name)
    contract_type = str(contract.get("type") or "literal")
    value_type = schema_value_types(contract_type)
    numeric_value: dict[str, Any] = {"type": "number"}
    for bound in ("minimum", "maximum"):
        if bound in contract:
            numeric_value[bound] = contract[bound]
    string_value: dict[str, Any] = {"type": "string", "maxLength": 200}
    if "enum" in contract:
        string_value["enum"] = list(contract["enum"])
    vector_value: dict[str, Any] = {
        "type": "array",
        "maxItems": 48,
        "items": {"type": "number"},
    }
    lengths = [int(value) for value in contract.get("lengths") or ()]
    if lengths:
        vector_value["minItems"] = min(lengths)
        vector_value["maxItems"] = max(lengths)
    structured_json: dict[str, Any] = {
        "type": "string",
        "maxLength": 4000,
    }
    matrix4_value: dict[str, Any] = {
        "type": "array",
        "minItems": 4,
        "maxItems": 4,
        "items": {
            "type": "array",
            "minItems": 4,
            "maxItems": 4,
            "items": {"type": "number"},
        },
    }
    carriers = {
        "number": ("numeric_value", numeric_value),
        "string": ("string_value", string_value),
        "boolean": (
            "boolean_value",
            {
                "type": "boolean",
                **({"enum": [True]} if operator == "box" and name == "center" else {}),
            },
        ),
        "vector": ("vector_value", vector_value),
        "structured_json": ("structured_json", structured_json),
        "matrix4": ("matrix4_value", matrix4_value),
    }
    properties: dict[str, Any] = {
        "name": {"type": "string", "enum": [name]},
        "value_type": {"enum": value_type},
    }
    required = ["name", "value_type"]
    selected_types = value_type if len(value_type) > 1 else value_type[:1]
    for selected_type in selected_types:
        carrier_name, carrier_schema = carriers[selected_type]
        properties[carrier_name] = carrier_schema
        required.append(carrier_name)
    return {
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": properties,
    }


def _parameter_schema(operator: str) -> dict[str, Any]:
    names = sorted(OPERATOR_PARAMETER_CONTRACTS.get(operator, ()))
    if not names:
        # ``parameters.maxItems`` is zero for this operator. An item schema is
        # still supplied because strict structured-output providers require it.
        return _parameter_variant(operator, "__no_parameters_allowed__")
    return {
        "anyOf": [
            _parameter_variant(operator, name)
            for name in names
        ],
    }


def author_node_schema(allowed_operators: list[str]) -> dict[str, Any]:
    """Return operator- and arity-discriminated strict AST node variants."""

    allowed = set(allowed_operators)

    def variants(
        kind: str,
        operators: set[str] | frozenset[str],
        *,
        minimum_inputs: int,
        maximum_inputs: int,
    ) -> list[dict[str, Any]]:
        items = []
        for operator in sorted(set(operators) & allowed):
            parameter_names = OPERATOR_PARAMETER_CONTRACTS.get(operator, ())
            items.append({
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "id",
                    "kind",
                    "operator",
                    "inputs",
                    "parameters",
                    "semantic_role",
                ],
                "properties": {
                    "id": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 80,
                    },
                    "kind": {"enum": [kind]},
                    "operator": {"enum": [operator]},
                    "inputs": {
                        "type": "array",
                        "minItems": minimum_inputs,
                        "maxItems": maximum_inputs,
                        "items": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 80,
                        },
                    },
                    "parameters": {
                        "type": "array",
                        "minItems": _REQUIRED_PARAMETER_COUNTS.get(operator, 0),
                        "maxItems": len(parameter_names),
                        "items": _parameter_schema(operator),
                    },
                    "semantic_role": {
                        "type": "string",
                        "maxLength": 80,
                    },
                },
            })
        return items

    node_variants = [
        *variants(
            "primitive",
            OPERATORS_BY_KIND["primitive"],
            minimum_inputs=0,
            maximum_inputs=0,
        ),
        *variants(
            "transform",
            OPERATORS_BY_KIND["transform"],
            minimum_inputs=1,
            maximum_inputs=1,
        ),
        *variants(
            "modifier",
            OPERATORS_BY_KIND["modifier"],
            minimum_inputs=1,
            maximum_inputs=1,
        ),
        *variants(
            "pattern",
            OPERATORS_BY_KIND["pattern"],
            minimum_inputs=1,
            maximum_inputs=1,
        ),
        *variants(
            "boolean",
            {"difference"},
            minimum_inputs=2,
            maximum_inputs=2,
        ),
        *variants(
            "boolean",
            {"union", "intersection"},
            minimum_inputs=2,
            maximum_inputs=4,
        ),
        *variants(
            "composition",
            {"attach"},
            minimum_inputs=2,
            maximum_inputs=4,
        ),
        *variants(
            "composition",
            {"bridge"},
            minimum_inputs=2,
            maximum_inputs=2,
        ),
        *variants(
            "macro",
            set(OPERATORS_BY_KIND["macro"]) - {"bridge"},
            minimum_inputs=1,
            maximum_inputs=4,
        ),
        *variants(
            "macro",
            {"bridge"},
            minimum_inputs=2,
            maximum_inputs=2,
        ),
    ]
    return {"anyOf": node_variants}


__all__ = ["author_node_schema"]
