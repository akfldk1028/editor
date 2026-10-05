"""Persist one compiled creative MASS as a portable research folder."""

from __future__ import annotations

import csv
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable, Sequence
import uuid

from backend.app.modules.design.generation.maas.agents.elevation_agent.projection import render_mesh_views, triangle_normals


RESEARCH_BUNDLE_SCHEMA = "arr.maas.creative_mass_research_bundle.v1"
ELEVATION_RESEARCH_SCHEMA = (
    "arr.maas.prelegal_elevation_research_handoff.v1"
)


def write_creative_mass_research_bundle(
    candidate: dict[str, Any],
    *,
    run_directory: Path,
    run_id: str,
    pnu: str,
) -> dict[str, Any]:
    candidate_id = str(candidate.get("candidate_id") or "").strip()
    program_hash = str(candidate.get("program_hash") or "").strip()
    geometry_hash = str(candidate.get("geometry_hash") or "").strip()
    program = candidate.get("geometry_program")
    mesh = candidate.get("mesh")
    if (
        not candidate_id
        or not program_hash
        or not geometry_hash
        or not isinstance(program, dict)
        or not isinstance(mesh, dict)
    ):
        raise ValueError("creative MASS research bundle input is incomplete")
    vertices = mesh.get("vertices")
    triangles = mesh.get("triangles")
    if not isinstance(vertices, list) or not isinstance(triangles, list):
        raise ValueError("creative MASS research bundle requires indexed mesh")

    root = run_directory.resolve()
    mass_directory = (root / "masses" / candidate_id).resolve()
    if mass_directory.parent.parent != root:
        raise ValueError("candidate_id escapes the run directory")
    program_directory = mass_directory / "program"
    transforms_directory = mass_directory / "transforms"
    mesh_directory = mass_directory / "mesh"
    views_directory = mass_directory / "views"
    research_directory = mass_directory / "elevation-research"
    for directory in (
        program_directory,
        transforms_directory,
        mesh_directory,
        views_directory,
        research_directory,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    identity = {
        "run_id": run_id,
        "candidate_id": candidate_id,
        "program_hash": program_hash,
        "geometry_hash": geometry_hash,
        "pnu": pnu,
    }
    paths = {
        "geometry_program": program_directory / "geometry-program.json",
        "author_evidence": program_directory / "author-evidence.json",
        "matrix4_trace": transforms_directory / "matrix4-trace.json",
        "indexed_mesh": mesh_directory / "indexed-mesh.json",
        "vertices_csv": mesh_directory / "vertices.csv",
        "triangles_csv": mesh_directory / "triangles.csv",
        "obj": mesh_directory / "mass.obj",
        "floor_guides": research_directory / "floor-guides.json",
        "camera_poses": research_directory / "camera-poses.json",
        "surface_normals": research_directory / "surface-normals.json",
        "facade_planes": research_directory / "facade-planes.json",
        "elevation_handoff": research_directory / "handoff.json",
    }
    _write_json_atomic(paths["geometry_program"], {
        "identity": identity,
        "geometry_program": program,
    })
    _write_json_atomic(paths["author_evidence"], {
        "identity": identity,
        "author_evidence": candidate.get("author_evidence") or {},
    })
    _write_json_atomic(paths["matrix4_trace"], {
        "identity": identity,
        "matrix4_trace": candidate.get("matrix4_trace") or [],
    })
    _write_json_atomic(paths["indexed_mesh"], {
        "identity": identity,
        "vertex_count": len(vertices),
        "triangle_count": len(triangles),
        "vertices": vertices,
        "triangles": triangles,
    })
    _write_csv_atomic(
        paths["vertices_csv"],
        ("vertex_id", "x", "y", "z"),
        (
            (index, *[float(value) for value in vertex])
            for index, vertex in enumerate(vertices)
        ),
    )
    _write_csv_atomic(
        paths["triangles_csv"],
        ("triangle_id", "a", "b", "c"),
        (
            (index, *[int(value) for value in triangle])
            for index, triangle in enumerate(triangles)
        ),
    )
    _write_text_atomic(
        paths["obj"],
        _obj_text(vertices, triangles, identity),
    )

    views = render_mesh_views(
        vertices,
        triangles,
        views_directory,
        execution_id=candidate_id,
    )
    view_payload = {
        view.view: {
            "path": f"views/{view.view}.png",
            "sha256": view.sha256,
            "width_px": view.width_px,
            "height_px": view.height_px,
            "projection": "orthographic",
            "projection_axes": view.projection_axes,
            "view_matrix4": view.view_matrix4,
            "projected_bounds_m": view.projected_bounds,
            "depth_range_m": view.depth_range,
        }
        for view in views
    }
    floor_guides = [
        float(value)
        for value in (
            (candidate.get("storey_evidence") or {}).get(
                "floor_elevations_m"
            )
            or ()
        )
    ]
    bounds = (candidate.get("mesh_evidence") or {}).get("bounds") or ()
    if len(bounds) != 2:
        bounds = [
            [
                min(float(vertex[index]) for vertex in vertices)
                for index in range(3)
            ],
            [
                max(float(vertex[index]) for vertex in vertices)
                for index in range(3)
            ],
        ]
    normals = triangle_normals(vertices, triangles)
    stable_face_ids = [
        sha256(
            (
                f"{geometry_hash}:{index}:"
                + ",".join(str(int(value)) for value in triangle)
            ).encode("utf-8")
        ).hexdigest()[:20]
        for index, triangle in enumerate(triangles)
    ]
    facade_planes = _facade_planes(bounds[0], bounds[1])
    _write_json_atomic(paths["floor_guides"], {
        "identity": identity,
        "authority": "authored_prelegal_storey_contract",
        "floor_guides_m": floor_guides,
    })
    _write_json_atomic(paths["camera_poses"], {
        "identity": identity,
        "views": view_payload,
    })
    _write_json_atomic(paths["surface_normals"], {
        "identity": identity,
        "stable_face_ids": stable_face_ids,
        "triangle_normals": normals,
    })
    _write_json_atomic(paths["facade_planes"], {
        "identity": identity,
        "facade_planes": facade_planes,
    })
    handoff = {
        "schema_version": ELEVATION_RESEARCH_SCHEMA,
        "status": "prelegal_research_ready",
        "identity": identity,
        "geometry_mutation_allowed": False,
        "indexed_mesh": {
            "path": "mesh/indexed-mesh.json",
            "vertex_count": len(vertices),
            "triangle_count": len(triangles),
            "stable_face_ids": stable_face_ids,
        },
        "program_path": "program/geometry-program.json",
        "matrix4_trace_path": "transforms/matrix4-trace.json",
        "floor_guides_m": floor_guides,
        "facade_planes": facade_planes,
        "views": view_payload,
        "missing_final_authorities": [
            "certified_legal_geometry",
            "parking_acceptance",
            "certified_floor_capacity_plan",
            "selector_acceptance",
        ],
    }
    _write_json_atomic(paths["elevation_handoff"], handoff)

    artifact_records = {
        name: {
            "path": path.relative_to(mass_directory).as_posix(),
            "sha256": _file_sha256(path),
        }
        for name, path in paths.items()
    }
    artifact_records["views"] = {
        "paths": {
            view: {
                "path": f"views/{view}.png",
                "sha256": payload["sha256"],
            }
            for view, payload in view_payload.items()
        }
    }
    manifest_path = mass_directory / "manifest.json"
    manifest = {
        "schema_version": RESEARCH_BUNDLE_SCHEMA,
        "status": "prelegal_research_ready",
        "identity": identity,
        "geometry_authority": "indexed_mesh_from_compiled_geometry_program",
        "geometry_mutation_allowed": False,
        "artifacts": artifact_records,
    }
    _write_json_atomic(manifest_path, manifest)
    return {
        "mass_directory": mass_directory.relative_to(root).as_posix(),
        "mass_manifest": manifest_path.relative_to(root).as_posix(),
        "elevation_research_handoff": paths[
            "elevation_handoff"
        ].relative_to(root).as_posix(),
        "manifest": manifest,
    }


def _obj_text(
    vertices: Sequence[Sequence[float]],
    triangles: Sequence[Sequence[int]],
    identity: dict[str, str],
) -> str:
    lines = [
        "# MAAS exact compiled indexed mesh",
        f"# program_hash {identity['program_hash']}",
        f"# geometry_hash {identity['geometry_hash']}",
    ]
    lines.extend(
        "v " + " ".join(format(float(value), ".12g") for value in vertex)
        for vertex in vertices
    )
    lines.extend(
        "f " + " ".join(str(int(value) + 1) for value in triangle)
        for triangle in triangles
    )
    return "\n".join(lines) + "\n"


def _facade_planes(
    minimum: Sequence[float],
    maximum: Sequence[float],
) -> list[dict[str, Any]]:
    minx, miny, minz = (float(value) for value in minimum)
    maxx, maxy, maxz = (float(value) for value in maximum)
    return [
        {
            "view": "front",
            "normal": [0, -1, 0],
            "origin": [minx, miny, minz],
            "extent_m": [maxx - minx, maxz - minz],
        },
        {
            "view": "right",
            "normal": [1, 0, 0],
            "origin": [maxx, miny, minz],
            "extent_m": [maxy - miny, maxz - minz],
        },
        {
            "view": "back",
            "normal": [0, 1, 0],
            "origin": [maxx, maxy, minz],
            "extent_m": [maxx - minx, maxz - minz],
        },
        {
            "view": "left",
            "normal": [-1, 0, 0],
            "origin": [minx, maxy, minz],
            "extent_m": [maxy - miny, maxz - minz],
        },
    ]


def _write_csv_atomic(
    path: Path,
    header: Iterable[str],
    rows: Iterable[Iterable[Any]],
) -> None:
    temporary = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(tuple(header))
        writer.writerows(rows)
    temporary.replace(path)


def _write_text_atomic(path: Path, content: str) -> None:
    temporary = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    _write_text_atomic(
        path,
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


__all__ = [
    "ELEVATION_RESEARCH_SCHEMA",
    "RESEARCH_BUNDLE_SCHEMA",
    "write_creative_mass_research_bundle",
]
