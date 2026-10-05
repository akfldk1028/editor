"""Operation schema helpers for conversational/direct MAAS editing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class InteractionTarget:
    kind: str = "mass"
    floor_index: int | None = None
    edge_index: int | None = None
    face_id: str | None = None


@dataclass(frozen=True)
class MassOperation:
    type: str
    target: InteractionTarget = field(default_factory=InteractionTarget)
    delta_m: float | None = None
    delta_floors: int | None = None
    factor: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)


def _target_from_operation(operation: dict[str, Any]) -> InteractionTarget:
    target = operation.get("target") or operation.get("face") or {}
    if not isinstance(target, dict):
        target = {}
    edge_index = operation.get("edge_index", target.get("edge_index"))
    floor_index = operation.get("floor_index", target.get("floor_index"))
    return InteractionTarget(
        kind=str(target.get("kind") or target.get("face_type") or operation.get("target_kind") or "mass"),
        floor_index=int(floor_index) if floor_index is not None else None,
        edge_index=int(edge_index) if edge_index is not None else None,
        face_id=str(target.get("face_id")) if target.get("face_id") is not None else None,
    )


def normalize_operation(operation: dict[str, Any]) -> MassOperation:
    if not isinstance(operation, dict):
        raise ValueError("operation must be an object")
    op_type = str(operation.get("type") or "")
    if op_type == "push_pull_height":
        op_type = "push_pull_face"
    if op_type not in {"push_pull_face", "offset_edge", "scale_footprint", "reshape_floor_plate"}:
        raise ValueError("operation.type must be push_pull_face, offset_edge, scale_footprint, or reshape_floor_plate")

    delta_m = operation.get("delta_m")
    delta_floors = operation.get("delta_floors")
    factor = operation.get("factor")
    return MassOperation(
        type=op_type,
        target=_target_from_operation(operation),
        delta_m=float(delta_m) if delta_m is not None else None,
        delta_floors=int(delta_floors) if delta_floors is not None else None,
        factor=float(factor) if factor is not None else None,
        raw=dict(operation),
    )


def append_operation_history(feature: dict[str, Any], operation: MassOperation, notes: list[str]) -> dict[str, Any]:
    out = dict(feature)
    props = dict(out.get("properties") or {})
    history = list(props.get("operation_history") or [])
    history.append({
        "type": operation.type,
        "target": {
            "kind": operation.target.kind,
            "floor_index": operation.target.floor_index,
            "edge_index": operation.target.edge_index,
            "face_id": operation.target.face_id,
        },
        "delta_m": operation.delta_m,
        "delta_floors": operation.delta_floors,
        "factor": operation.factor,
        "notes": notes,
    })
    props["operation_history"] = history
    out["properties"] = props
    return out


def operation_to_dict(operation: MassOperation) -> dict[str, Any]:
    return {
        "type": operation.type,
        "target": {
            "kind": operation.target.kind,
            "floor_index": operation.target.floor_index,
            "edge_index": operation.target.edge_index,
            "face_id": operation.target.face_id,
        },
        "delta_m": operation.delta_m,
        "delta_floors": operation.delta_floors,
        "factor": operation.factor,
    }


__all__ = ["InteractionTarget", "MassOperation", "append_operation_history", "normalize_operation", "operation_to_dict"]
