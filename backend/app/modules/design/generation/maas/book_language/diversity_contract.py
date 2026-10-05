"""Label-free diversity contracts measured from the certified final mesh."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any

from backend.app.modules.design.generation.maas.program_massing.competition_gestalt import competition_gestalt_key


_CLUSTER_QUANTUM = 0.20
_MEASURED_FIELDS = (
    "floor_area_by_height",
    "setback_transition_sequence",
    "roof_breakline_profile",
    "plan_profile",
)


def _quantize(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return [_quantize(item) for item in value]
    try:
        return int(round(float(value) / _CLUSTER_QUANTUM))
    except (TypeError, ValueError):
        return 0


def certified_mesh_cluster_key_from_payload(payload: dict[str, Any]) -> str:
    """Hash coarse measured gestalt without a named morphology label."""

    quantized = {
        field: _quantize(payload.get(field) or ())
        for field in _MEASURED_FIELDS
    }
    encoded = json.dumps(
        quantized,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def certified_mesh_cluster_key(source: Any) -> str:
    gestalt = competition_gestalt_key(source)
    return certified_mesh_cluster_key_from_payload(gestalt.evidence())


__all__ = [
    "certified_mesh_cluster_key",
    "certified_mesh_cluster_key_from_payload",
]
