"""Serialize one authoritative MASS floor product for API consumers.

The frontend must display the compiler and hard-gate evidence verbatim.  This
module deliberately normalizes existing typed evidence and never estimates
floor counts, areas, parking, or legal ratios from a rendered image.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryProgram


def serialize_mass_product_evidence(
    *,
    program: GeometryProgram,
    capacity: Mapping[str, Any] | None = None,
    hard_gates: Mapping[str, Any] | None = None,
    passport: Mapping[str, Any] | None = None,
    compilation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return stable floor/legal/parking/matrix fields for archive manifests."""

    metadata = _mapping(program.metadata)
    capacity_evidence = _merged_capacity(capacity, passport)
    passport_payload = _mapping(passport)
    gates = _mapping(hard_gates)
    law_evidence = _stage_evidence(passport, "law")
    parking_evidence = _first_mapping(
        gates.get("parking"),
        _stage_evidence(passport, "parking"),
    )
    shared_floor = _first_mapping(
        metadata.get("shared_floor_contract"),
        capacity_evidence.get("shared_floor_contract"),
        law_evidence.get("shared_floor_contract"),
    )
    totals = _mapping(shared_floor.get("totals"))
    projected = _first_mapping(
        gates.get("projectedMetrics"),
        gates.get("projected_metrics"),
        law_evidence.get("projectedMetrics"),
        law_evidence.get("projected_metrics"),
    )
    floorwise = _first_mapping(
        metadata.get("floorwise_legal_matrix_stack"),
        metadata.get("floorwise_projection"),
    )
    matrix_stack = _matrix_stack(program, compilation)
    floor_capacity_plan_hash = _first_text(
        shared_floor.get("floor_capacity_plan_hash"),
        _mapping(shared_floor.get("identity")).get("floor_capacity_plan_hash"),
        capacity_evidence.get("floor_capacity_plan_hash"),
        floorwise.get("floor_capacity_plan_hash"),
        passport_payload.get("floor_capacity_plan_hash"),
    )
    floor_contract_hash = _first_text(
        shared_floor.get("floor_contract_hash"),
        projected.get("floor_contract_hash"),
        law_evidence.get("floor_contract_hash"),
    )
    compilation_payload = _mapping(compilation)
    compilation_metrics = _mapping(compilation_payload.get("metrics"))
    elevation_payload = _mapping(passport_payload.get("elevation_evidence"))
    final_legal_geometry_hash = resolve_final_legal_geometry_identity(
        compilation=compilation_payload,
        passport=passport_payload,
        elevation=elevation_payload,
    )
    upstream_geometry_hashes = {
        key: value
        for key, value in (
            (
                "authored_geometry_hash",
                _first_text(
                    compilation_payload.get("authored_geometry_hash"),
                    compilation_metrics.get("authored_geometry_hash"),
                ),
            ),
            (
                "capacity_geometry_hash",
                _first_text(
                    compilation_payload.get("capacity_geometry_hash"),
                    compilation_metrics.get("capacity_geometry_hash"),
                ),
            ),
        )
        if value
    }

    return {
        "final_legal_geometry_hash": final_legal_geometry_hash,
        "upstream_geometry_hashes": upstream_geometry_hashes,
        "num_floors": _first_integer(
            totals.get("num_floors"),
            floorwise.get("floor_count"),
        ),
        "floor_height_m": _first_number(
            shared_floor.get("floor_height_m"),
            _derived_floor_height(floorwise),
        ),
        "total_floor_area_m2": _first_number(
            totals.get("total_floor_area_m2"),
            projected.get("floor_area_m2"),
            capacity_evidence.get("total_floor_area_m2"),
        ),
        "bcr_pct": _first_number(
            projected.get("bcr_pct"),
            law_evidence.get("bcr_pct"),
        ),
        "far_pct": _first_number(
            projected.get("far_pct"),
            totals.get("far_pct"),
            capacity_evidence.get("far_pct"),
        ),
        "parking_required": _first_integer(
            parking_evidence.get("required_spaces"),
            _mapping(parking_evidence.get("requirement")).get("required_spaces"),
        ),
        "parking_provided": _first_integer(
            parking_evidence.get("provided_spaces"),
        ),
        "floor_contract_hash": floor_contract_hash,
        "floor_capacity_plan_hash": floor_capacity_plan_hash,
        "elevation_status": _elevation_status(passport),
        "matrix_convention": _first_text(
            floorwise.get("matrix_convention"),
            metadata.get("matrix_convention"),
            "row_major_column_vector" if matrix_stack else "",
        ),
        "floor_matrix_stack": matrix_stack,
    }


def floor_capacity_plan_hash(
    *,
    program: GeometryProgram | None = None,
    capacity: Mapping[str, Any] | None = None,
    passport: Mapping[str, Any] | None = None,
) -> str:
    """Extract the law-derived floor-plan identity without deriving a new one."""

    return resolve_floor_capacity_plan_identity(
        program=program,
        capacity=capacity,
        passport=passport,
    )


def resolve_final_legal_geometry_identity(
    *,
    compilation: Mapping[str, Any] | None = None,
    passport: Mapping[str, Any] | None = None,
    render: Mapping[str, Any] | None = None,
    elevation: Mapping[str, Any] | None = None,
    archive: Mapping[str, Any] | None = None,
    additional_hashes: Sequence[Any] = (),
) -> str:
    """Resolve one final projected legal geometry identity.

    Authored and capacity geometry hashes are deliberately not candidates.
    They remain useful provenance, but cannot prove the final projected mesh.
    """

    compilation_payload = _mapping(compilation)
    passport_payload = _mapping(passport)
    render_payload = _mapping(render)
    elevation_payload = _mapping(elevation)
    archive_payload = _mapping(archive)
    final_hashes = {
        text
        for value in (
            compilation_payload.get("final_legal_geometry_hash"),
            compilation_payload.get("geometry_hash"),
            passport_payload.get("final_legal_geometry_hash"),
            render_payload.get("final_legal_geometry_hash"),
            elevation_payload.get("final_legal_geometry_hash"),
            archive_payload.get("final_legal_geometry_hash"),
            *additional_hashes,
        )
        if (text := str(value or "").strip())
    }
    if len(final_hashes) > 1:
        raise ValueError("final legal geometry identity mismatch")
    return next(iter(final_hashes), "")


def resolve_floor_capacity_plan_identity(
    *,
    program: GeometryProgram | None = None,
    capacity: Mapping[str, Any] | None = None,
    passport: Mapping[str, Any] | None = None,
    shared_floor_contract: Mapping[str, Any] | None = None,
    additional_hashes: Sequence[Any] = (),
    require_shared_contract: bool = False,
    unresolved: str = "",
) -> str:
    """Resolve one capacity-plan identity and reject competing sources."""

    metadata = _mapping(program.metadata) if program is not None else {}
    supplied_capacity = _mapping(capacity)
    passport_capacity = _stage_evidence(passport, "capacity")
    contracts = [
        row
        for row in (
            shared_floor_contract,
            metadata.get("shared_floor_contract"),
            supplied_capacity.get("shared_floor_contract"),
            passport_capacity.get("shared_floor_contract"),
        )
        if isinstance(row, Mapping)
    ]
    contract_hashes = {
        text
        for contract in contracts
        for value in (
            contract.get("floor_capacity_plan_hash"),
            _mapping(contract.get("identity")).get(
                "floor_capacity_plan_hash"
            ),
        )
        if (text := str(value or "").strip())
    }
    if require_shared_contract and (not contracts or not contract_hashes):
        raise ValueError(
            "production archive replay requires shared floor capacity plan identity"
        )
    stack = _mapping(metadata.get("floorwise_legal_matrix_stack"))
    all_hashes = {
        text
        for value in (
            *contract_hashes,
            supplied_capacity.get("floor_capacity_plan_hash"),
            passport_capacity.get("floor_capacity_plan_hash"),
            _mapping(passport).get("floor_capacity_plan_hash"),
            stack.get("floor_capacity_plan_hash"),
            *additional_hashes,
        )
        if (text := str(value or "").strip())
    }
    if len(all_hashes) > 1:
        raise ValueError("floor capacity plan identity mismatch")
    return next(iter(all_hashes), str(unresolved or "").strip())


def _merged_capacity(
    supplied: Mapping[str, Any] | None,
    passport: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        **_stage_evidence(passport, "capacity"),
        **_mapping(supplied),
    }


def _stage_evidence(
    passport: Mapping[str, Any] | None,
    stage_id: str,
) -> dict[str, Any]:
    payload = _mapping(passport)
    for stage in payload.get("stages") or ():
        if isinstance(stage, Mapping) and str(stage.get("id") or "") == stage_id:
            return _mapping(stage.get("evidence"))
    return {}


def _matrix_stack(
    program: GeometryProgram,
    compilation: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in _mapping(compilation).get("trace") or ():
        if not isinstance(row, Mapping) or not _is_matrix4(row.get("matrix4")):
            continue
        result.append({
            "node_id": str(row.get("node_id") or ""),
            "semantic_role": "",
            "matrix4": [
                [float(value) for value in matrix_row]
                for matrix_row in row["matrix4"]
            ],
        })
    if result:
        return result
    for node in program.topological_nodes():
        if node.operator != "matrix4":
            continue
        matrix = node.parameters.get("matrix4")
        if not _is_matrix4(matrix):
            continue
        result.append({
            "node_id": node.id,
            "semantic_role": node.semantic_role,
            "matrix4": [[float(value) for value in row] for row in matrix],
        })
    return result


def _elevation_status(passport: Mapping[str, Any] | None) -> str:
    payload = _mapping(passport)
    direct = _mapping(payload.get("elevation_evidence"))
    if direct.get("status"):
        return str(direct["status"])
    graph = _mapping(payload.get("activation_graph"))
    for node in graph.get("nodes") or ():
        if (
            isinstance(node, Mapping)
            and str(node.get("id") or "") == "elevation:result"
            and node.get("status")
        ):
            return str(node["status"])
    return "not_evaluated"


def _derived_floor_height(floorwise: Mapping[str, Any]) -> float | None:
    height = _number_or_none(floorwise.get("height_m"))
    floors = _integer_or_none(floorwise.get("floor_count"))
    if height is None or floors is None or floors <= 0:
        return None
    return height / floors


def _first_mapping(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, Mapping):
            return dict(value)
    return {}


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _first_number(*values: Any) -> float | None:
    for value in values:
        number = _number_or_none(value)
        if number is not None:
            return number
    return None


def _number_or_none(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _first_integer(*values: Any) -> int | None:
    for value in values:
        number = _integer_or_none(value)
        if number is not None:
            return number
    return None


def _integer_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _is_matrix4(value: Any) -> bool:
    return (
        isinstance(value, (list, tuple))
        and len(value) == 4
        and all(
            isinstance(row, (list, tuple))
            and len(row) == 4
            and all(isinstance(item, (int, float)) for item in row)
            for row in value
        )
    )


__all__ = [
    "floor_capacity_plan_hash",
    "resolve_final_legal_geometry_identity",
    "resolve_floor_capacity_plan_identity",
    "serialize_mass_product_evidence",
]
