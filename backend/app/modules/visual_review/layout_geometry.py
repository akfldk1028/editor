"""Persist a floor's layout geometry as JSON alongside its rendered artifacts.

The review JSON records *metrics* about rooms — areas, widths, aspect ratios —
but never the coordinates themselves, so every downstream consumer had to
re-derive geometry from the SVG (which is what `cad_handoff.svg_to_dxf` does).
Writing the `LayoutCandidate` verbatim gives consumers a contract they can
validate instead of a drawing they have to parse.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from backend.app.schemas.layout import LayoutCandidate

LAYOUT_GEOMETRY_SCHEMA_VERSION = 1
LAYOUT_GEOMETRY_CONTRACT = "planm-floor-geometry/v1"


def _point(value: Any) -> list[float] | None:
    """Coerce one coordinate pair, or None when it is not a finite pair."""
    try:
        x, z = value
        x = float(x)
        z = float(z)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(x) and math.isfinite(z)):
        return None
    return [x, z]


def _point_list(points: Any) -> list[list[float]]:
    coerced = [_point(value) for value in points or ()]
    return [point for point in coerced if point is not None]


def _rooms(rooms: Any, *, category: str) -> list[dict[str, Any]]:
    return [
        {
            "room_id": room.room_id,
            "space_type": room.space_type,
            "category": category,
            "polygon": _point_list(room.polygon),
        }
        for room in rooms
    ]


def _opening(opening: Any) -> dict[str, Any] | None:
    """Serialise one opening, or None when its geometry is unusable.

    The renderer skips malformed openings and still emits its artifacts, so this
    must too — a bad coordinate should cost the plan one opening, not its whole
    review.
    """
    start = _point(opening.start)
    end = _point(opening.end)
    if start is None or end is None:
        return None
    try:
        clear_width = float(opening.clear_width)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(clear_width):
        return None
    return {
        "opening_id": opening.opening_id,
        "kind": opening.kind,
        "connects": list(opening.connects),
        "start": start,
        "end": end,
        "clear_width": clear_width,
    }


def build_floor_geometry(
    layout: LayoutCandidate,
    *,
    boundary: list[tuple[float, float]] | None = None,
    use_type: str | None = None,
) -> dict[str, Any]:
    """Serialise a layout candidate into the floor-geometry contract.

    Coordinates are the layout's own metres on the plan plane, unchanged — no
    normalisation or rounding, so a consumer reproduces the same geometry the
    SVG was drawn from.
    """
    payload: dict[str, Any] = {
        "contract_version": LAYOUT_GEOMETRY_CONTRACT,
        "schema_version": LAYOUT_GEOMETRY_SCHEMA_VERSION,
        "project_id": layout.project_id,
        "candidate_id": layout.candidate_id,
        "floor_index": layout.floor_index,
        "units": "m",
        "rooms": _rooms(layout.rooms, category="room")
        + _rooms(layout.circulation, category="circulation"),
        "openings": [
            serialised
            for serialised in (_opening(opening) for opening in layout.openings)
            if serialised is not None
        ],
    }
    if use_type is not None:
        payload["use_type"] = use_type
    if boundary:
        payload["boundary"] = _point_list(boundary)
    if layout.remote_stair_footprint is not None:
        payload["remote_stair_footprint"] = _point_list(layout.remote_stair_footprint)
    return payload


def write_floor_geometry(
    layout: LayoutCandidate,
    path: str | Path,
    *,
    boundary: list[tuple[float, float]] | None = None,
    use_type: str | None = None,
) -> Path:
    """Write the floor-geometry artifact and return its path."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            build_floor_geometry(layout, boundary=boundary, use_type=use_type),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return target


__all__ = [
    "LAYOUT_GEOMETRY_CONTRACT",
    "LAYOUT_GEOMETRY_SCHEMA_VERSION",
    "build_floor_geometry",
    "write_floor_geometry",
]
