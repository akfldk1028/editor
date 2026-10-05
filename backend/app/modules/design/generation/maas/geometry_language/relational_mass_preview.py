"""Zero-paid visual checkpoint for ordinary and relational MASS language."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from backend.app.modules.design.generation.maas.paid_provider_budget import paid_provider_budget_snapshot

from backend.app.modules.design.generation.maas.geometry_language.affine_matrix import compose_matrix4, matrix4_to_lists, rotation_matrix4, translation_matrix4
from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryNode, GeometryProgram
from backend.app.modules.design.generation.maas.geometry_language.base_seeds import base_seed_program
from backend.app.modules.design.generation.maas.geometry_language.compiler import compile_geometry_program
from backend.app.modules.design.generation.maas.geometry_language.programs import architectural_shape_programs
from backend.app.modules.design.generation.maas.geometry_language.render import materialize_isometric_thumbnail, render_compilation_preview


PREVIEW_SCHEMA_VERSION = "arr.maas.relational_mass_preview.v1"
BOARD_SIZE = (1920, 1320)
SHORTLIST_SIZE = (1800, 650)


def _font(size: int, *, bold: bool = False):
    path = Path(
        r"C:\Windows\Fonts\segoeuib.ttf"
        if bold
        else r"C:\Windows\Fonts\segoeui.ttf"
    )
    if path.is_file():
        return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _interlocking_plate_program() -> GeometryProgram:
    base = base_seed_program("slab")
    circular = GeometryNode(
        "relational_disc",
        "modifier",
        "circularize",
        inputs=(base.root_id,),
        parameters={"segments": 48},
        semantic_role="inhabited_plate",
        provenance={
            "source": "relational_mass_preview",
            "architectural_use": "elliptic inhabited plate",
        },
    )
    matrices = [
        matrix4_to_lists(translation_matrix4((0.0, 0.0, 0.0))),
        matrix4_to_lists(compose_matrix4(
            rotation_matrix4((12.0, 0.0, 18.0)),
            translation_matrix4((0.20, 0.05, 0.12)),
        )),
        matrix4_to_lists(compose_matrix4(
            rotation_matrix4((-10.0, 8.0, -16.0)),
            translation_matrix4((-0.18, 0.10, 0.20)),
        )),
    ]
    array = GeometryNode(
        "interlocking_plates",
        "pattern",
        "matrix_array",
        inputs=(circular.id,),
        parameters={"matrices": matrices},
        semantic_role="connected_plate_field",
        provenance={
            "source": "relational_mass_preview",
            "architectural_use": (
                "interlocking occupied plates; capability test, not precedent copy"
            ),
        },
    )
    return replace(
        base.with_nodes(
            (*base.nodes, circular, array),
            root_id=array.id,
        ),
        name="relational_19_interlocking_plates",
        metadata={
            **base.metadata,
            "preview_lane": "interlocking_plate_relation",
            "not_a_named_recipe": True,
        },
    )


def _continuous_section_program() -> GeometryProgram:
    base = base_seed_program("bar")
    sweep = GeometryNode(
        "continuous_section_sweep",
        "modifier",
        "profile_sweep_3d",
        inputs=(base.root_id,),
        parameters={
            "path": [
                [-3.0, -1.1, 0.0],
                [-1.2, -1.0, 0.25],
                [0.4, -0.25, 0.85],
                [1.8, 0.75, 1.45],
                [3.1, 1.05, 1.0],
            ],
            "require_connected": True,
        },
        semantic_role="continuous_floor_wall_roof_section",
        provenance={
            "source": "relational_mass_preview",
            "architectural_use": (
                "continuous occupiable section; capability test, not precedent copy"
            ),
        },
    )
    return replace(
        base.with_nodes(
            (*base.nodes, sweep),
            root_id=sweep.id,
        ),
        name="relational_20_continuous_section",
        metadata={
            **base.metadata,
            "preview_lane": "continuous_section_relation",
            "not_a_named_recipe": True,
        },
    )


def preview_programs() -> tuple[GeometryProgram, ...]:
    """Return exactly twenty deterministic zero-paid language candidates."""

    ordinary_and_relational = architectural_shape_programs()
    return (
        *ordinary_and_relational,
        _interlocking_plate_program(),
        _continuous_section_program(),
    )


def _candidate_label(program: GeometryProgram, index: int) -> str:
    lane = str(program.metadata.get("preview_lane") or "")
    if lane:
        return lane.replace("_", " ")
    return program.name.removeprefix("shape_").replace("_", " ")


def _render_board(
    candidates: list[dict[str, Any]],
    *,
    output_path: Path,
    pnu: str,
) -> None:
    image = Image.new("RGB", BOARD_SIZE, "#e8eef5")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, BOARD_SIZE[0], 80), fill="#07111f")
    draw.text(
        (24, 16),
        f"MAAS SAME-SITE LANGUAGE CHECK · PNU {pnu} · 20 MASS",
        font=_font(28, bold=True),
        fill="#f8fafc",
    )
    draw.text(
        (24, 51),
        "ZERO PAID CALLS · NORMALIZED GEOMETRY PREVIEW · LAW / PARKING NOT YET EVALUATED",
        font=_font(15, bold=True),
        fill="#fbbf24",
    )
    cell_w = 384
    cell_h = 310
    for index, candidate in enumerate(candidates):
        column = index % 5
        row = index // 5
        x = column * cell_w
        y = 80 + row * cell_h
        draw.rectangle(
            (x + 4, y + 4, x + cell_w - 4, y + cell_h - 4),
            fill="#ffffff",
            outline="#cbd5e1",
            width=1,
        )
        thumbnail_path = candidate.get("thumbnail_png")
        if thumbnail_path and Path(thumbnail_path).is_file():
            with Image.open(thumbnail_path) as source:
                thumb = source.convert("RGB")
                thumb.thumbnail((360, 222), Image.Resampling.LANCZOS)
                px = x + (cell_w - thumb.width) // 2
                py = y + 14
                image.paste(thumb, (px, py))
        else:
            draw.text(
                (x + 28, y + 90),
                "GEOMETRY REJECT",
                font=_font(22, bold=True),
                fill="#b91c1c",
            )
        draw.text(
            (x + 12, y + 243),
            f"{index + 1:02d}  {candidate['label'][:34]}",
            font=_font(15, bold=True),
            fill="#0f172a",
        )
        status_color = "#15803d" if candidate["status"] == "compiled" else "#b91c1c"
        draw.text(
            (x + 12, y + 269),
            (
                f"{candidate['status'].upper()} · "
                f"{candidate.get('triangle_count', 0)} tri · "
                f"{str(candidate.get('geometry_hash') or '')[:10]}"
            ),
            font=_font(13),
            fill=status_color,
        )
        draw.text(
            (x + 12, y + 289),
            "LAW/PARKING: NOT EVALUATED",
            font=_font(12, bold=True),
            fill="#a16207",
        )
    image.save(output_path, format="PNG", optimize=True)


def _render_shortlist(
    candidates: list[dict[str, Any]],
    *,
    output_path: Path,
    pnu: str,
) -> None:
    image = Image.new("RGB", SHORTLIST_SIZE, "#07111f")
    draw = ImageDraw.Draw(image)
    draw.text(
        (22, 14),
        f"MAAS ZERO-PAID SHORTLIST 3 · PNU {pnu}",
        font=_font(28, bold=True),
        fill="#f8fafc",
    )
    draw.text(
        (22, 50),
        "VLM NOT YET SPENT · GEOMETRY COMPILED · EXACT LAW / CAPACITY / PARKING STILL REQUIRED",
        font=_font(15, bold=True),
        fill="#fbbf24",
    )
    card_w = 600
    for index, candidate in enumerate(candidates):
        x = index * card_w
        draw.rectangle(
            (x + 8, 84, x + card_w - 8, 642),
            fill="#f8fafc",
            outline="#38bdf8",
            width=2,
        )
        with Image.open(candidate["preview_png"]) as source:
            preview = source.convert("RGB")
            preview.thumbnail((570, 450), Image.Resampling.LANCZOS)
            image.paste(
                preview,
                (x + (card_w - preview.width) // 2, 96),
            )
        draw.text(
            (x + 18, 555),
            f"{candidate['candidate_id']} · {candidate['label'][:42]}",
            font=_font(16, bold=True),
            fill="#0f172a",
        )
        draw.text(
            (x + 18, 582),
            (
                f"CONNECTED {candidate['component_count'] == 1} · "
                f"{candidate['triangle_count']} tri · "
                f"{candidate['geometry_hash'][:12]}"
            ),
            font=_font(14),
            fill="#166534",
        )
        draw.text(
            (x + 18, 610),
            "VISIBLE PREVIEW ONLY — NOT A LEGAL ACCEPTANCE",
            font=_font(13, bold=True),
            fill="#b45309",
        )
    image.save(output_path, format="PNG", optimize=True)


def render_relational_mass_preview(
    output_dir: str | Path,
    pnu: str,
) -> dict[str, Any]:
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    candidates: list[dict[str, Any]] = []
    for index, program in enumerate(preview_programs(), start=1):
        compilation = compile_geometry_program(program)
        preview_path = output / f"mass-{index:02d}.png"
        program_path = output / f"mass-{index:02d}.geometry-program.json"
        program_path.write_text(
            json.dumps(program.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        row: dict[str, Any] = {
            "candidate_id": f"mass-{index:02d}",
            "label": _candidate_label(program, index),
            "program_name": program.name,
            "program_hash": program.program_hash(),
            "program_json": str(program_path),
            "status": compilation.status,
            "component_count": int(
                compilation.metrics.get("component_count") or 0
            ),
            "triangle_count": int(
                compilation.metrics.get("triangle_count") or 0
            ),
            "geometry_hash": str(compilation.geometry_hash or ""),
            "issues": [
                issue.to_dict() if hasattr(issue, "to_dict") else str(issue)
                for issue in compilation.issues
            ],
            "law_status": "not_evaluated",
            "parking_status": "not_evaluated",
            "paid_vlm_status": "not_requested",
        }
        if compilation.status == "compiled":
            render_compilation_preview(
                compilation,
                preview_path,
                title=f"{index:02d} {row['label']}",
            )
            thumbnail_path = materialize_isometric_thumbnail(preview_path)
            row["preview_png"] = str(preview_path)
            row["thumbnail_png"] = str(thumbnail_path)
        candidates.append(row)

    compiled = [item for item in candidates if item["status"] == "compiled"]
    # The continuous-section probe remains visible on the twenty-board, but
    # its current narrow strip does not yet prove enough occupiable depth for
    # paid review. Keep a connected split-wing/bridge candidate instead.
    preferred_ids = ("mass-19", "mass-17", "mass-15")
    shortlist = [
        next(item for item in compiled if item["candidate_id"] == candidate_id)
        for candidate_id in preferred_ids
        if any(item["candidate_id"] == candidate_id for item in compiled)
    ]
    if len(shortlist) < 3:
        used_ids = {item["candidate_id"] for item in shortlist}
        shortlist.extend(
            item for item in compiled
            if item["candidate_id"] not in used_ids
        )
    shortlist = shortlist[:3]

    board_path = output / "maas-same-site-20.png"
    shortlist_path = output / "maas-vlm-shortlist-3.png"
    _render_board(candidates, output_path=board_path, pnu=str(pnu))
    _render_shortlist(shortlist, output_path=shortlist_path, pnu=str(pnu))

    manifest = {
        "schema_version": PREVIEW_SCHEMA_VERSION,
        "status": "geometry_preview_only",
        "pnu": str(pnu),
        "candidate_count": len(candidates),
        "compiled_count": len(compiled),
        "shortlist_count": len(shortlist),
        "paid_provider_request_count": 0,
        "law_status": "not_evaluated",
        "parking_status": "not_evaluated",
        "board_png": str(board_path),
        "board_sha256": hashlib.sha256(board_path.read_bytes()).hexdigest(),
        "shortlist_png": str(shortlist_path),
        "shortlist_sha256": hashlib.sha256(
            shortlist_path.read_bytes(),
        ).hexdigest(),
        "shortlist_candidate_ids": [
            item["candidate_id"] for item in shortlist
        ],
        "candidates": candidates,
        "paid_provider_budget_snapshot": paid_provider_budget_snapshot(),
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {**manifest, "manifest_json": str(manifest_path)}


__all__ = [
    "PREVIEW_SCHEMA_VERSION",
    "preview_programs",
    "render_relational_mass_preview",
]
