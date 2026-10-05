"""Compile and render the BOOK p.3 base-volume grammar in isolation."""

from __future__ import annotations

from dataclasses import replace
from math import cos, radians, sin
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from backend.app.modules.design.generation.maas.book_language.base_volume_contract import BOOK_BASE_VOLUME_SPECS
from backend.app.modules.design.generation.maas.book_language.corpus_contract import BOOK_ORIENTATIONS

from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryNode, GeometryProgram
from backend.app.modules.design.generation.maas.geometry_language.base_seeds import base_seed_program
from backend.app.modules.design.generation.maas.geometry_language.compiler import CompilationResult, compile_geometry_program


def book_base_volume_program(
    label: str,
    orientation: str,
    *,
    seed_id: str = "block",
) -> GeometryProgram:
    base = base_seed_program(seed_id)
    selector = GeometryNode(
        id="book_base_volume",
        kind="modifier",
        operator="book_base_volume",
        inputs=(base.root_id,),
        parameters={"label": label, "orientation": orientation},
        semantic_role="book_p3_base_volume",
        provenance={"source": "BOOK", "page": 3},
    )
    return replace(
        base,
        nodes=(*base.nodes, selector),
        root_id=selector.id,
        name=f"book_p3_{seed_id}_{label.replace('/', '_')}__{orientation}",
        metadata={
            **base.metadata,
            "book_base_volume": {
                "label": label,
                "orientation": orientation,
                "base_seed": seed_id,
            },
        },
    )


def audit_book_base_volumes() -> dict[str, Any]:
    rows = []
    compilations: dict[tuple[str, str], CompilationResult] = {}
    for spec in BOOK_BASE_VOLUME_SPECS:
        for orientation in BOOK_ORIENTATIONS:
            compilation = compile_geometry_program(book_base_volume_program(spec.label, orientation))
            compilations[(spec.label, orientation)] = compilation
            measured = float(compilation.metrics.get("volume", 0.0))
            rows.append({
                "label": spec.label,
                "orientation": orientation,
                "topology": spec.topology,
                "requested_fraction": spec.fraction,
                "measured_fraction": round(measured, 9),
                "fraction_error": round(abs(measured - spec.fraction), 9),
                "status": compilation.status,
                "component_count": int(compilation.metrics.get("component_count", 0)),
                "vertex_count": int(compilation.metrics.get("vertex_count", 0)),
                "geometry_hash": compilation.geometry_hash,
            })
    issues = []
    for row in rows:
        if row["status"] != "compiled":
            issues.append(f"compile_failed:{row['label']}:{row['orientation']}")
        if row["fraction_error"] > 1e-7:
            issues.append(f"fraction_mismatch:{row['label']}:{row['orientation']}")
        if row["component_count"] != 1:
            issues.append(f"disconnected:{row['label']}:{row['orientation']}")
    return {
        "schema_version": "arr.maas.book_base_volume_audit.v1",
        "hard_pass": not issues,
        "issues": issues,
        "rows": rows,
        "_compilations": compilations,
    }


def render_book_base_volume_audit(output_path: str | Path) -> Path:
    audit = audit_book_base_volumes()
    compilations = audit.pop("_compilations")
    cell_width, cell_height = 300, 235
    header_height, row_label_width = 76, 120
    width = row_label_width + cell_width * len(BOOK_BASE_VOLUME_SPECS)
    height = header_height + cell_height * len(BOOK_ORIENTATIONS)
    board = Image.new("RGB", (width, height), "#eef2f7")
    draw = ImageDraw.Draw(board)
    draw.text((18, 12), "BOOK p.3 BASE VOLUMES — exact cell grammar / one shared unit-cube scale", fill="#111827")
    for column, spec in enumerate(BOOK_BASE_VOLUME_SPECS):
        x = row_label_width + column * cell_width
        draw.text((x + 12, 42), f"{spec.label}  {spec.topology}", fill="#374151")
    for row, orientation in enumerate(BOOK_ORIENTATIONS):
        y = header_height + row * cell_height
        draw.text((12, y + 18), orientation.replace("_", " "), fill="#111827")
        for column, spec in enumerate(BOOK_BASE_VOLUME_SPECS):
            result = compilations[(spec.label, orientation)]
            panel = _shared_scale_panel(result, cell_width - 16, cell_height - 38)
            board.paste(panel, (row_label_width + column * cell_width + 8, y + 8))
            draw.text(
                (row_label_width + column * cell_width + 12, y + cell_height - 25),
                f"V={result.metrics.get('volume', 0):.4f}  C={result.metrics.get('component_count', 0)}",
                fill="#374151",
            )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output.with_suffix(".tmp.png")
    board.save(temporary_output)
    temporary_output.replace(output)
    return output


def _shared_scale_panel(result: CompilationResult, width: int, height: int) -> Image.Image:
    """Draw every selection inside the same projected unit-cube frame."""

    panel = Image.new("RGB", (width, height), "#ffffff")
    draw = ImageDraw.Draw(panel, "RGBA")
    cube = np.asarray([
        (0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
        (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1),
    ], dtype=float)
    solid = np.asarray(result.vertices, dtype=float)
    points = np.vstack((cube, solid)) - np.asarray((0.5, 0.5, 0.5))
    yaw, pitch = radians(35.0), radians(28.0)
    rz = np.asarray(((cos(yaw), -sin(yaw), 0), (sin(yaw), cos(yaw), 0), (0, 0, 1)))
    rx = np.asarray(((1, 0, 0), (0, cos(pitch), -sin(pitch)), (0, sin(pitch), cos(pitch))))
    rotated = points @ rz.T @ rx.T
    projected = rotated[:, :2]
    cube_projected = projected[:8]
    span = np.ptp(cube_projected, axis=0)
    scale = min((width - 58) / max(span[0], 1e-9), (height - 44) / max(span[1], 1e-9))
    screen = np.empty_like(projected)
    screen[:, 0] = width / 2 + projected[:, 0] * scale
    screen[:, 1] = height / 2 - projected[:, 1] * scale
    solid_screen = screen[8:]
    solid_rotated = rotated[8:]
    faces = np.asarray(result.triangles, dtype=int)
    light = np.asarray((0.35, -0.45, 0.82), dtype=float)
    light /= np.linalg.norm(light)
    ordered = sorted(range(len(faces)), key=lambda index: float(solid_rotated[faces[index], 2].mean()))
    for face_index in ordered:
        face = faces[face_index]
        a, b, c = solid_rotated[face]
        normal = np.cross(b - a, c - a)
        norm = float(np.linalg.norm(normal))
        if norm <= 1e-12:
            continue
        normal /= norm
        intensity = 0.40 + 0.56 * abs(float(np.dot(normal, light)))
        color = (int(225 * intensity), int(148 * intensity), int(56 * intensity), 245)
        draw.polygon([tuple(solid_screen[index]) for index in face], fill=color, outline=(126, 69, 28, 130))
    for first, second in (
        (0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4),
        (0, 4), (1, 5), (2, 6), (3, 7),
    ):
        draw.line((tuple(screen[first]), tuple(screen[second])), fill=(92, 112, 138, 125), width=1)
    return panel


__all__ = [
    "audit_book_base_volumes", "book_base_volume_program",
    "render_book_base_volume_audit",
]
