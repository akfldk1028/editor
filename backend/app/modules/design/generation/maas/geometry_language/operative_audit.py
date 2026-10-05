"""Exhaustive BOOK base-operative geometry audit (30 x 11 x 3)."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from PIL import Image, ImageDraw

from backend.app.modules.design.generation.maas.book_language.corpus_contract import BASE_OPERATIVES, BOOK_ORIENTATIONS
from backend.app.modules.design.generation.maas.program_massing import book_operation_variants, compose_program_with_book_operations, program_seed_sequences

from backend.app.modules.design.generation.maas.geometry_language.base_seeds import base_seed_program
from backend.app.modules.design.generation.maas.geometry_language.book_adapter import apply_book_projection_to_geometry_program
from backend.app.modules.design.generation.maas.geometry_language.compiler import CompilationResult, compile_geometry_program
from backend.app.modules.design.generation.maas.geometry_language.render import render_compilation_preview


_REPRESENTATIVE_VARIATIONS = (0, 5, 10)


def audit_book_operatives() -> dict[str, Any]:
    base = base_seed_program("block")
    program_seed = program_seed_sequences("gymnasium")[0]
    rows = []
    representative: dict[tuple[str, str], CompilationResult] = {}
    issues = []
    for operative in BASE_OPERATIVES:
        hashes = {orientation: [] for orientation in BOOK_ORIENTATIONS}
        components = []
        failures = []
        variants = book_operation_variants(operative.verb, count=11)
        for variation_index, call in enumerate(variants):
            for orientation in BOOK_ORIENTATIONS:
                sequence = compose_program_with_book_operations(
                    program_seed,
                    (call,),
                    base_volume_label="1/4",
                    orientation=orientation,
                )
                program = apply_book_projection_to_geometry_program(base, sequence)
                compilation = compile_geometry_program(program)
                hashes[orientation].append(compilation.geometry_hash)
                components.append(int(compilation.metrics.get("component_count", 0)))
                if compilation.status != "compiled":
                    failures.append(f"{variation_index}:{orientation}:{compilation.status}")
                if variation_index == _REPRESENTATIVE_VARIATIONS[BOOK_ORIENTATIONS.index(orientation)]:
                    representative[(operative.verb, orientation)] = compilation
        unique_by_orientation = {
            orientation: len(set(values))
            for orientation, values in hashes.items()
        }
        row = {
            "verb": operative.verb,
            "page": operative.page,
            "transformation": operative.transformation,
            "cardinality": operative.cardinality,
            "compile_count": sum(len(values) for values in hashes.values()),
            "unique_geometry_count": len(set(sum(hashes.values(), []))),
            "unique_by_orientation": unique_by_orientation,
            "maximum_component_count": max(components or (0,)),
            "failures": failures,
        }
        rows.append(row)
        if failures:
            issues.append(f"compile_failure:{operative.verb}")
        if set(unique_by_orientation.values()) != {11}:
            issues.append(f"variation_collapse:{operative.verb}:{unique_by_orientation}")
        if row["unique_geometry_count"] != 33:
            issues.append(f"orientation_collapse:{operative.verb}:{row['unique_geometry_count']}")
        if row["maximum_component_count"] != 1:
            issues.append(f"disconnected:{operative.verb}:{row['maximum_component_count']}")
    return {
        "schema_version": "arr.maas.book_operative_audit.v1",
        "hard_pass": not issues,
        "issues": issues,
        "scope": "1/4",
        "variation_count": 11,
        "orientation_count": 3,
        "compile_count": sum(row["compile_count"] for row in rows),
        "rows": rows,
        "_representative": representative,
    }


def render_book_operative_audit(output_path: str | Path) -> Path:
    audit = audit_book_operatives()
    representative = audit.pop("_representative")
    columns, cell_width, cell_height = 6, 420, 238
    row_count = (len(BASE_OPERATIVES) + columns - 1) // columns
    board = Image.new("RGB", (columns * cell_width, 46 + row_count * cell_height), "#e8edf4")
    draw = ImageDraw.Draw(board)
    draw.text((16, 15), "BOOK OPERATIVES — v01 long / v06 short / v11 vertical (all 990 compiled separately)", fill="#111827")
    with TemporaryDirectory() as temporary_directory:
        temporary = Path(temporary_directory)
        for index, operative in enumerate(BASE_OPERATIVES):
            x = (index % columns) * cell_width
            y = 46 + (index // columns) * cell_height
            draw.text((x + 10, y + 8), f"p.{operative.page} {operative.verb.upper()}", fill="#111827")
            for orientation_index, orientation in enumerate(BOOK_ORIENTATIONS):
                compilation = representative[(operative.verb, orientation)]
                preview = temporary / f"{index:02d}_{orientation_index}.png"
                render_compilation_preview(compilation, preview, title=f"{operative.verb} {orientation}")
                with Image.open(preview) as image:
                    panel = image.crop((6, 6, 444, 319)).resize((128, 174))
                    board.paste(panel, (x + 8 + orientation_index * 136, y + 29))
                draw.text((x + 11 + orientation_index * 136, y + 207), orientation.replace("_axis", ""), fill="#4b5563")
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output.with_suffix(".tmp.png")
    board.save(temporary_output)
    temporary_output.replace(output)
    return output


__all__ = ["audit_book_operatives", "render_book_operative_audit"]
