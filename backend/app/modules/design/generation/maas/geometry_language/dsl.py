"""Small, deterministic, SSA-normalized text DSL for geometry programs."""

from __future__ import annotations

import ast as python_ast
import re
from typing import Any

from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryNode, GeometryProgram, OPERATORS_BY_KIND


ALIASES = {
    "move": "translate",
    "subtract": "difference",
    "intersect": "intersection",
    "extrude_polygon": "extruded_polygon",
}
OPERATOR_KIND = {
    operator: kind
    for kind, operators in OPERATORS_BY_KIND.items()
    for operator in operators
}
# The textual spelling resolves ambiguous core/macro names to the more direct
# core operation. JSON AST authors can still select the macro kind explicitly.
OPERATOR_KIND.update({"bridge": "composition", "cut_corner": "modifier"})
POSITIONAL_PARAMETERS = {
    "box": ("width", "depth", "height"),
    "cylinder": ("radius", "height"),
    "wedge": ("width", "depth", "start_height", "end_height"),
}
IDENTIFIER = re.compile(r"[^A-Za-z0-9_.:-]+")


class GeometryDslError(ValueError):
    pass


def parse_geometry_dsl(source: str, *, name: str = "geometry_dsl") -> GeometryProgram:
    """Parse assignment-only DSL and normalize reassignment into acyclic SSA nodes."""
    bindings: dict[str, str] = {}
    versions: dict[str, int] = {}
    nodes: list[GeometryNode] = []
    last_id = ""

    def lower_call(call: python_ast.Call, target_name: str, line_number: int) -> str:
        """Lower recursive Solid expressions into the same SSA node graph.

        The surface DSL remains assignment-oriented for reliable LLM output,
        but a model may naturally emit ``scale(box(...), ...)`` or a deeper
        ``difference(bend(union(...)), taper(...))`` expression.  Every nested
        call is still typed, validated and assigned a deterministic hidden node
        ID; this is syntax normalization, never a geometry fallback.
        """
        if not isinstance(call.func, python_ast.Name):
            raise GeometryDslError(f"line {line_number}: operator must be a simple name")
        operator = ALIASES.get(call.func.id.lower(), call.func.id.lower())
        kind = OPERATOR_KIND.get(operator)
        if kind is None:
            raise GeometryDslError(f"line {line_number}: unsupported operator {operator}")
        prepared_args: list[python_ast.AST] = []
        temporary_bindings: list[str] = []
        for argument_index, argument in enumerate(call.args):
            if isinstance(argument, python_ast.Call):
                nested_target = f"{target_name}__input_{argument_index + 1}"
                nested_id = lower_call(argument, nested_target, line_number)
                temporary_name = f"__nested_{len(nodes)}_{argument_index}"
                bindings[temporary_name] = nested_id
                temporary_bindings.append(temporary_name)
                prepared_args.append(python_ast.Name(id=temporary_name, ctx=python_ast.Load()))
            else:
                prepared_args.append(argument)
        prepared_call = python_ast.Call(
            func=call.func,
            args=prepared_args,
            keywords=call.keywords,
        )
        try:
            input_ids, parameters = _parse_call(
                prepared_call,
                kind,
                operator,
                bindings,
                line_number,
            )
        finally:
            for temporary_name in temporary_bindings:
                bindings.pop(temporary_name, None)
        versions[target_name] = versions.get(target_name, 0) + 1
        suffix = "" if versions[target_name] == 1 else f"__{versions[target_name]}"
        node_id = _safe_identifier(f"{target_name}{suffix}")
        nodes.append(GeometryNode(node_id, kind, operator, tuple(input_ids), parameters))
        return node_id

    for line_number, raw_line in enumerate(source.splitlines(), 1):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("mass "):
            line = line[5:].lstrip()
        try:
            statement = python_ast.parse(line, mode="exec").body
        except SyntaxError as exc:
            raise GeometryDslError(f"line {line_number}: invalid syntax") from exc
        if len(statement) != 1 or not isinstance(statement[0], python_ast.Assign) or len(statement[0].targets) != 1:
            raise GeometryDslError(f"line {line_number}: expected one assignment")
        target = statement[0].targets[0]
        if not isinstance(target, python_ast.Name) or not isinstance(statement[0].value, python_ast.Call):
            raise GeometryDslError(f"line {line_number}: assignment must target a name and call an operator")
        call = statement[0].value
        node_id = lower_call(call, target.id, line_number)
        bindings[target.id] = node_id
        last_id = node_id
    if not nodes:
        raise GeometryDslError("geometry DSL is empty")
    root_id = bindings.get("result", last_id)
    program = GeometryProgram(tuple(nodes), root_id, name=name, metadata={"source": "text_dsl", "ssa_normalized": True})
    errors = [issue for issue in program.validate() if issue.severity == "error"]
    if errors:
        raise GeometryDslError("invalid geometry program: " + ", ".join(issue.code for issue in errors))
    return program


def program_to_dsl(program: GeometryProgram) -> str:
    """Serialize a program using explicit parameters and stable node references."""
    lines: list[str] = []
    for node in program.topological_nodes():
        args = list(node.inputs)
        args.extend(f"{key}={_literal(value)}" for key, value in sorted(node.parameters.items()))
        lines.append(f"mass {node.id} = {node.operator}({', '.join(args)})")
    return "\n".join(lines)


def _parse_call(
    call: python_ast.Call,
    kind: str,
    operator: str,
    bindings: dict[str, str],
    line_number: int,
) -> tuple[list[str], dict[str, Any]]:
    positional = list(call.args)
    input_ids: list[str] = []
    if kind != "primitive":
        minimum_inputs = 2 if kind in {"boolean", "composition"} else 1
        while positional and isinstance(positional[0], python_ast.Name):
            name = positional.pop(0).id
            if name not in bindings:
                raise GeometryDslError(f"line {line_number}: unknown solid {name}")
            input_ids.append(bindings[name])
            if kind not in {"boolean", "composition"}:
                break
        if len(input_ids) < minimum_inputs:
            raise GeometryDslError(f"line {line_number}: {operator} needs {minimum_inputs} solid input(s)")
    parameters: dict[str, Any] = {}
    parameter_names = POSITIONAL_PARAMETERS.get(operator, ())
    if operator == "translate" and len(positional) == 3:
        parameters["vector"] = [_literal_value(item, line_number) for item in positional]
        positional.clear()
    for index, value in enumerate(positional):
        if index >= len(parameter_names):
            raise GeometryDslError(f"line {line_number}: unexpected positional parameter for {operator}")
        parameters[parameter_names[index]] = _literal_value(value, line_number)
    for keyword in call.keywords:
        if keyword.arg is None:
            raise GeometryDslError(f"line {line_number}: **kwargs are not allowed")
        key = re.sub(r"(?<!^)(?=[A-Z])", "_", keyword.arg).lower()
        parameters[key] = _literal_value(keyword.value, line_number)
    return input_ids, parameters


def _literal_value(value: python_ast.AST, line_number: int) -> Any:
    try:
        result = python_ast.literal_eval(value)
    except (ValueError, TypeError) as exc:
        raise GeometryDslError(f"line {line_number}: parameters must be literal values") from exc
    if not isinstance(result, (str, int, float, bool, list, tuple, dict, type(None))):
        raise GeometryDslError(f"line {line_number}: unsupported literal")
    return list(result) if isinstance(result, tuple) else result


def _safe_identifier(value: str) -> str:
    cleaned = IDENTIFIER.sub("_", value).strip("_")
    if not cleaned or not cleaned[0].isalpha():
        cleaned = f"node_{cleaned}"
    return cleaned[:80]


def _literal(value: Any) -> str:
    return repr(value)


__all__ = ["GeometryDslError", "parse_geometry_dsl", "program_to_dsl"]
