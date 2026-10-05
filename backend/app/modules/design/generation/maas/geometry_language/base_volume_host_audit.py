"""Cross-host audit proving that BOOK p.3 is not a small-fragment catalog.

The p.3 cell grammar selects a relative part of a live host.  Applying the
same 1/1 or 1/2 choice to SLAB, BAR and TOWER must therefore preserve those
architectural proportions: a full SLAB is a broad plate/podium, not a cube.
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from PIL import Image, ImageDraw

from backend.app.modules.design.generation.maas.book_language.base_volume_contract import BOOK_BASE_VOLUME_SPECS
from backend.app.modules.design.generation.maas.book_language.corpus_contract import BOOK_ORIENTATIONS

from backend.app.modules.design.generation.maas.geometry_language.base_seeds import BASE_SEED_SPECS, base_seed_program
from backend.app.modules.design.generation.maas.geometry_language.base_volume_audit import book_base_volume_program
from backend.app.modules.design.generation.maas.geometry_language.compiler import CompilationResult, compile_geometry_program
from backend.app.modules.design.generation.maas.geometry_language.render import render_compilation_preview


def audit_book_base_volumes_across_hosts() -> dict[str, Any]:
    """Compile 6 scopes × 3 orientations × 5 proportion hosts."""

    rows: list[dict[str, Any]] = []
    compilations: dict[tuple[str, str, str], CompilationResult] = {}
    issues: list[str] = []
    box_derived_ids = {
        item.seed_id for item in BASE_SEED_SPECS if item.primitive_operator == "box"
    }
    host_volumes = {
        item.seed_id: float(
            compile_geometry_program(base_seed_program(item.seed_id)).metrics.get("volume", 0.0)
        )
        for item in BASE_SEED_SPECS
    }

    for seed in BASE_SEED_SPECS:
        host_volume = host_volumes[seed.seed_id]
        for spec in BOOK_BASE_VOLUME_SPECS:
            for orientation in BOOK_ORIENTATIONS:
                result = compile_geometry_program(book_base_volume_program(
                    spec.label,
                    orientation,
                    seed_id=seed.seed_id,
                ))
                compilations[(seed.seed_id, spec.label, orientation)] = result
                selected_volume = float(result.metrics.get("volume", 0.0))
                measured_fraction = selected_volume / host_volume if host_volume > 1e-12 else 0.0
                fraction_error = abs(measured_fraction - spec.fraction)
                row = {
                    "base_seed": seed.seed_id,
                    "base_seed_label": seed.label,
                    "architectural_use": seed.architectural_use,
                    "normalized_scale": list(seed.normalized_scale),
                    "base_volume": spec.label,
                    "orientation": orientation,
                    "requested_fraction": spec.fraction,
                    "host_volume": round(host_volume, 9),
                    "selected_volume": round(selected_volume, 9),
                    "measured_host_fraction": round(measured_fraction, 9),
                    "fraction_error": round(fraction_error, 9),
                    "exact_fraction_host": seed.seed_id in box_derived_ids,
                    "status": result.status,
                    "component_count": int(result.metrics.get("component_count", 0)),
                    "geometry_hash": result.geometry_hash,
                }
                rows.append(row)
                if result.status != "compiled":
                    issues.append(f"compile:{seed.seed_id}:{spec.label}:{orientation}")
                if row["component_count"] != 1:
                    issues.append(f"disconnected:{seed.seed_id}:{spec.label}:{orientation}")
                if seed.seed_id in box_derived_ids and fraction_error > 1e-7:
                    issues.append(f"fraction:{seed.seed_id}:{spec.label}:{orientation}")
                if seed.seed_id not in box_derived_ids and not (0.0 < measured_fraction <= 1.0 + 1e-7):
                    issues.append(f"profiled_host_selection:{spec.label}:{orientation}")

    return {
        "schema_version": "arr.maas.book_base_volume_host_audit.v1",
        "hard_pass": not issues,
        "issues": issues,
        "compile_count": len(rows),
        "exact_box_host_count": len(box_derived_ids),
        "contract": "base_volume_fraction_x_orientation_x_base_seed_proportion",
        "rows": rows,
        "_compilations": compilations,
    }


def render_book_base_volume_host_audit(output_path: str | Path) -> Path:
    """Render all 90 host/scope/orientation states on one comparison board."""

    audit = audit_book_base_volumes_across_hosts()
    compilations = audit.pop("_compilations")
    cell_width, cell_height = 246, 184
    label_width, header_height = 196, 92
    width = label_width + cell_width * len(BOOK_BASE_VOLUME_SPECS)
    height = header_height + cell_height * len(BASE_SEED_SPECS)
    board = Image.new("RGB", (width, height), "#e9eef5")
    draw = ImageDraw.Draw(board)
    draw.text((18, 14), "BOOK p.3 x BASE-SEED HOST — 90 connected states", fill="#111827")
    draw.text(
        (18, 37),
        "1/1 SLAB = wide plate / podium datum; fraction and proportion are independent axes",
        fill="#475569",
    )
    for column, spec in enumerate(BOOK_BASE_VOLUME_SPECS):
        draw.text((label_width + column * cell_width + 10, 67), spec.label, fill="#111827")

    with TemporaryDirectory() as temporary_directory:
        temporary = Path(temporary_directory)
        for row_index, seed in enumerate(BASE_SEED_SPECS):
            y = header_height + row_index * cell_height
            draw.text((14, y + 12), seed.label, fill="#111827")
            draw.text((14, y + 31), seed.architectural_use[:27], fill="#64748b")
            draw.text((14, y + 49), f"scale {seed.normalized_scale}", fill="#64748b")
            for column, spec in enumerate(BOOK_BASE_VOLUME_SPECS):
                x = label_width + column * cell_width
                for orientation_index, orientation in enumerate(BOOK_ORIENTATIONS):
                    result = compilations[(seed.seed_id, spec.label, orientation)]
                    preview = temporary / f"{seed.seed_id}_{column}_{orientation_index}.png"
                    render_compilation_preview(result, preview, title="")
                    with Image.open(preview) as image:
                        panel = image.crop((6, 6, 444, 319)).resize((72, 118))
                        board.paste(panel, (x + 5 + orientation_index * 78, y + 7))
                draw.text((x + 8, y + 132), "long      short     vertical", fill="#64748b")
                host_volume = next(
                    item["host_volume"] for item in audit["rows"]
                    if item["base_seed"] == seed.seed_id and item["base_volume"] == spec.label
                )
                draw.text((x + 8, y + 151), f"host V={host_volume:g} · selected {spec.label}", fill="#334155")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output.with_suffix(".tmp.png")
    board.save(temporary_output)
    temporary_output.replace(output)
    return output


__all__ = ["audit_book_base_volumes_across_hosts", "render_book_base_volume_host_audit"]
