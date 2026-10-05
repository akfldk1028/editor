"""Generate hash-bound elevation evidence from one compiled MASS."""

from __future__ import annotations

from pathlib import Path
from copy import deepcopy
import hashlib
import json
from typing import Any
import uuid

from backend.app.modules.design.generation.maas.mass_product_evidence import resolve_floor_capacity_plan_identity

from backend.app.modules.design.generation.maas.agents.elevation_agent.contract import ElevationBundle, certified_elevation_identity
from backend.app.modules.design.generation.maas.agents.elevation_agent.projection import render_mesh_views, triangle_normals

def generate_elevation_bundle(
    compilation: Any,
    output_root: str | Path,
    *,
    execution_id: str,
    shared_floor_contract: dict[str, Any] | None = None,
    floor_capacity_plan_hash: str = "",
    final_legal_geometry_hash: str = "",
    visual_hash: str = "",
    legal_floor_field_hash: str = "",
    candidate_actual_gfa_stop_hash: str = "",
    candidate_actual_gfa_stop_certificate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if str(getattr(compilation, "status", "")) != "compiled":
        raise ValueError("elevationAgent requires a compiled MASS")
    vertices = tuple(getattr(compilation, "vertices", ()) or ())
    triangles = tuple(getattr(compilation, "triangles", ()) or ())
    if not vertices or not triangles:
        raise ValueError("elevationAgent requires a non-empty indexed triangle mesh")
    program_hash = compilation.program.program_hash()
    geometry_hash = str(compilation.geometry_hash or "")
    shared_floor = (
        shared_floor_contract
        if isinstance(shared_floor_contract, dict)
        and shared_floor_contract.get("schema_version")
        == "arr.maas.shared_floor_contract.v1"
        else None
    )
    if shared_floor_contract is not None and shared_floor is None:
        raise ValueError("elevationAgent requires a valid shared-floor contract")
    resolved_floor_capacity_plan_hash = resolve_floor_capacity_plan_identity(
        shared_floor_contract=shared_floor,
        additional_hashes=(floor_capacity_plan_hash,),
    )
    resolved_certificate = (
        candidate_actual_gfa_stop_certificate
        if isinstance(candidate_actual_gfa_stop_certificate, dict)
        else (
            (shared_floor or {}).get(
                "candidate_actual_gfa_stop_certificate"
            )
            if isinstance(
                (shared_floor or {}).get(
                    "candidate_actual_gfa_stop_certificate"
                ),
                dict,
            )
            else None
        )
    )
    identity, selected_floor_count = certified_elevation_identity(
        execution_id=execution_id,
        program_hash=program_hash,
        geometry_hash=geometry_hash,
        final_legal_geometry_hash=(
            final_legal_geometry_hash
            or str(
                (shared_floor or {}).get(
                    "final_legal_geometry_hash"
                )
                or ""
            )
        ),
        visual_hash=(
            visual_hash
            or str((shared_floor or {}).get("visual_hash") or "")
        ),
        floor_capacity_plan_hash=resolved_floor_capacity_plan_hash,
        legal_floor_field_hash=(
            legal_floor_field_hash
            or str(
                (shared_floor or {}).get("legal_floor_field_hash")
                or ""
            )
        ),
        candidate_actual_gfa_stop_hash=(
            candidate_actual_gfa_stop_hash
            or str(
                (shared_floor or {}).get(
                    "candidate_actual_gfa_stop_hash"
                )
                or ""
            )
        ),
        candidate_actual_gfa_stop_certificate=resolved_certificate,
        shared_floor_contract=shared_floor,
    )
    floor_guides = _certified_floor_guides(
        shared_floor or {},
        selected_floor_count=selected_floor_count,
    )
    root = Path(output_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    views_directory = root / "views"
    views = render_mesh_views(
        vertices,
        triangles,
        views_directory,
        execution_id=execution_id,
    )
    bounds = getattr(compilation, "metrics", {}).get("bounds")
    if isinstance(bounds, list) and len(bounds) == 2:
        minimum, maximum = bounds
    else:
        minimum = [min(float(row[i]) for row in vertices) for i in range(3)]
        maximum = [max(float(row[i]) for row in vertices) for i in range(3)]
    condition_pack = {
        "schema_version": "arr.elevation_agent.condition_pack.v1",
        "final_geometry_hash": identity["final_geometry_hash"],
        "final_legal_geometry_hash": identity["final_legal_geometry_hash"],
        "visual_hash": identity["visual_hash"],
        "legal_floor_field_hash": identity["legal_floor_field_hash"],
        "candidate_actual_gfa_stop_hash": (
            identity["candidate_actual_gfa_stop_hash"]
        ),
        "candidate_actual_gfa_stop_certificate": deepcopy(
            resolved_certificate or {}
        ),
        "selected_floor_count": selected_floor_count,
        "identity": identity,
        "indexed_mesh": {
            "vertex_count": len(vertices),
            "triangle_count": len(triangles),
            "stable_face_ids": [
                hashlib.sha256(
                    f"{geometry_hash}:{index}:{','.join(str(int(value)) for value in triangle)}".encode()
                ).hexdigest()[:20]
                for index, triangle in enumerate(triangles)
            ],
        },
        "camera_poses": [
            {
                "view": view.view,
                "projection": "orthographic",
                "axes": view.projection_axes,
            }
            for view in views
        ],
        "silhouette": {
            view.view: {"projected_bounds": view.projected_bounds}
            for view in views
        },
        "metric_depth": {
            view.view: {"range_m": view.depth_range}
            for view in views
        },
        "surface_normals": triangle_normals(vertices, triangles),
        "floor_contract_hash": str(
            (shared_floor or {}).get("floor_contract_hash") or ""
        ),
        "floor_capacity_plan_hash": resolved_floor_capacity_plan_hash,
        "target_floor_areas_m2": [
            round(max(0.0, float(value)), 4)
            for value in (shared_floor or {}).get("target_floor_areas_m2", ())
        ],
        "capacity_alternative": deepcopy(
            (shared_floor or {}).get("capacity_alternative") or {}
        ),
        "floor_guides_m": floor_guides,
        "facade_planes": _facade_planes(minimum, maximum),
        "geometry_mutation_allowed": False,
    }
    condition_path = root / "condition-pack.json"
    _write_json_atomic(condition_path, condition_pack)
    manifest_path = root / "manifest.json"
    bundle = ElevationBundle(
        execution_id=execution_id,
        program_hash=program_hash,
        geometry_hash=geometry_hash,
        final_geometry_hash=identity["final_geometry_hash"],
        visual_hash=identity["visual_hash"],
        floor_capacity_plan_hash=resolved_floor_capacity_plan_hash,
        legal_floor_field_hash=identity["legal_floor_field_hash"],
        candidate_actual_gfa_stop_hash=(
            identity["candidate_actual_gfa_stop_hash"]
        ),
        candidate_actual_gfa_stop_certificate=deepcopy(
            resolved_certificate or {}
        ),
        output_directory=str(root),
        manifest_path=str(manifest_path),
        condition_pack_path=str(condition_path),
        views=views,
        condition_pack=condition_pack,
    )
    payload = bundle.to_dict()
    _write_json_atomic(manifest_path, payload)
    return payload


def _contract_floor_guides(contract: dict[str, Any]) -> list[float]:
    plates = contract.get("plates") if isinstance(contract.get("plates"), list) else []
    guides = sorted({
        round(float(value), 6)
        for plate in plates
        if isinstance(plate, dict) and plate.get("hard_pass")
        for value in (
            plate.get("bottom_height_m"),
            plate.get("top_height_m"),
        )
        if value is not None
    })
    if len(guides) < 2:
        raise ValueError("elevationAgent requires at least one accepted floor plate")
    return guides


def _certified_floor_guides(
    contract: dict[str, Any],
    *,
    selected_floor_count: int,
) -> list[float]:
    plates = (
        contract.get("plates")
        if isinstance(contract.get("plates"), list)
        else []
    )
    intervals: list[tuple[float, float]] = []
    for plate in plates:
        if not isinstance(plate, dict) or plate.get("hard_pass") is not True:
            raise ValueError(
                "elevationAgent selected floor count mismatch"
            )
        try:
            bottom = float(plate["bottom_height_m"])
            top = float(plate["top_height_m"])
        except (KeyError, TypeError, ValueError):
            raise ValueError(
                "elevationAgent requires certified floor guide heights"
            ) from None
        if top <= bottom:
            raise ValueError(
                "elevationAgent requires certified floor guide heights"
            )
        intervals.append((bottom, top))
    intervals.sort()
    if (
        len(intervals) != selected_floor_count
        or any(
            abs(intervals[index][0] - intervals[index - 1][1]) > 1e-6
            for index in range(1, len(intervals))
        )
    ):
        raise ValueError(
            "elevationAgent selected floor count mismatch"
        )
    guides = [
        round(intervals[0][0], 6),
        *[round(top, 6) for _bottom, top in intervals],
    ]
    if (
        len(guides) != selected_floor_count + 1
        or guides[-1] != round(intervals[-1][1], 6)
    ):
        raise ValueError(
            "elevationAgent certified terminal height mismatch"
        )
    return guides


def _floor_guides(minimum_z: float, maximum_z: float, interval: float = 3.3) -> list[float]:
    guides: list[float] = []
    value = minimum_z
    while value <= maximum_z + 1e-9 and len(guides) < 128:
        guides.append(round(value, 6))
        value += interval
    if not guides or guides[-1] < maximum_z:
        guides.append(round(maximum_z, 6))
    return guides


def _facade_planes(minimum: Any, maximum: Any) -> list[dict[str, Any]]:
    minx, miny, minz = (float(value) for value in minimum)
    maxx, maxy, maxz = (float(value) for value in maximum)
    return [
        {"view": "front", "normal": [0, -1, 0], "origin": [minx, miny, minz], "extent": [maxx - minx, maxz - minz]},
        {"view": "right", "normal": [1, 0, 0], "origin": [maxx, miny, minz], "extent": [maxy - miny, maxz - minz]},
        {"view": "back", "normal": [0, 1, 0], "origin": [maxx, maxy, minz], "extent": [maxx - minx, maxz - minz]},
        {"view": "left", "normal": [-1, 0, 0], "origin": [minx, maxy, minz], "extent": [maxy - miny, maxz - minz]},
    ]


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


__all__ = ["generate_elevation_bundle"]
