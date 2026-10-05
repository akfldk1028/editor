"""End-to-end audit for every source page and executable BOOK principle."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from PIL import Image, ImageDraw

from backend.app.modules.design.generation.maas.book_language.corpus_audit import audit_book_corpus
from backend.app.modules.design.generation.maas.book_language.corpus_contract import BOOK_ORIENTATIONS
from backend.app.modules.design.generation.maas.book_language.registry import build_book_language_registry
from backend.app.modules.design.generation.maas.program_massing import book_sentence_variants, compose_program_with_book_operations, program_seed_sequences

from backend.app.modules.design.generation.maas.geometry_language.base_seeds import base_seed_program
from backend.app.modules.design.generation.maas.geometry_language.base_volume_audit import audit_book_base_volumes
from backend.app.modules.design.generation.maas.geometry_language.book_adapter import apply_book_projection_to_geometry_program
from backend.app.modules.design.generation.maas.geometry_language.book_lowering_contract import BOOK_OPERATIVE_LOWERING
from backend.app.modules.design.generation.maas.geometry_language.compiler import CompilationResult, compile_geometry_program
from backend.app.modules.design.generation.maas.geometry_language.render import render_compilation_preview


_REPRESENTATIVE_VARIATIONS = (0, 5, 10)


def audit_book_pages() -> dict[str, Any]:
    """Validate source integrity, p.3 grammar and all 69 executable principles."""

    corpus = audit_book_corpus()
    registry = build_book_language_registry()
    base_volume = audit_book_base_volumes()
    base_volume.pop("_compilations", None)
    base = base_seed_program("block")
    program_seed = program_seed_sequences("gymnasium")[0]
    principle_rows: list[dict[str, Any]] = []
    representative: dict[tuple[str, str], CompilationResult] = {}
    issues: list[str] = []

    for principle in registry["principles"]:
        principle_id = str(principle["principle_id"])
        hashes = {orientation: [] for orientation in BOOK_ORIENTATIONS}
        failures: list[str] = []
        component_counts: list[int] = []
        lowered_operators: set[str] = set()
        variants = book_sentence_variants(
            tuple(principle["execution_verbs"]), count=11
        )
        for variation_index, calls in enumerate(variants):
            for orientation_index, orientation in enumerate(BOOK_ORIENTATIONS):
                sequence = compose_program_with_book_operations(
                    program_seed,
                    calls,
                    base_volume_label="1/4",
                    orientation=orientation,
                )
                try:
                    program = apply_book_projection_to_geometry_program(base, sequence)
                    compilation = compile_geometry_program(program)
                except Exception as exc:  # audit records the exact failing sentence
                    failures.append(
                        f"{variation_index}:{orientation}:{type(exc).__name__}:{exc}"
                    )
                    continue
                hashes[orientation].append(compilation.geometry_hash)
                lowered_operators.update(
                    node.operator for node in program.nodes
                    if node.provenance.get("source") == "book_recursive_projection"
                    and node.provenance.get("book_verb") == principle["execution_verbs"][0]
                )
                component_counts.append(
                    int(compilation.metrics.get("component_count", 0))
                )
                if compilation.status != "compiled":
                    failures.append(
                        f"{variation_index}:{orientation}:{compilation.status}"
                    )
                if variation_index == _REPRESENTATIVE_VARIATIONS[orientation_index]:
                    representative[(principle_id, orientation)] = compilation
        unique_by_orientation = {
            orientation: len(set(values))
            for orientation, values in hashes.items()
        }
        row_issues = []
        if failures:
            row_issues.append("compile_failure")
        if set(unique_by_orientation.values()) != {11}:
            row_issues.append("variation_collapse")
        maximum_components = max(component_counts or (0,))
        if maximum_components != 1:
            row_issues.append("disconnected")
        if principle["kind"] == "base_operative":
            lowering = BOOK_OPERATIVE_LOWERING[str(principle["label"])]
            if not lowering.required_operators.issubset(lowered_operators):
                row_issues.append("missing_required_lowering")
            if lowering.forbidden_operators & lowered_operators:
                row_issues.append("forbidden_lowering")
        row = {
            "principle_id": principle_id,
            "kind": principle["kind"],
            "label": principle["label"],
            "pages": list(principle["page_refs"]),
            "execution_verbs": list(principle["execution_verbs"]),
            "compile_count": sum(len(values) for values in hashes.values()),
            "unique_by_orientation": unique_by_orientation,
            "maximum_component_count": maximum_components,
            "lowered_operators": sorted(lowered_operators),
            "failures": failures,
            "hard_pass": not row_issues,
            "issues": row_issues,
        }
        principle_rows.append(row)
        issues.extend(f"{principle_id}:{item}" for item in row_issues)

    by_page: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in principle_rows:
        for page in row["pages"]:
            by_page[int(page)].append(row)
    page_rows = []
    for source_page in registry["pages"]:
        page = int(source_page["page"])
        principles = by_page.get(page, [])
        if page == 3:
            validation_mode = "exact_base_volume_geometry"
            page_pass = bool(base_volume["hard_pass"])
            compile_count = len(base_volume["rows"])
        elif principles:
            validation_mode = "recursive_principle_geometry"
            page_pass = all(item["hard_pass"] for item in principles)
            compile_count = sum(int(item["compile_count"]) for item in principles)
        else:
            validation_mode = "source_and_taxonomy_evidence"
            page_pass = bool(source_page.get("sha256")) and isinstance(
                source_page.get("ocr_lines"), list
            )
            compile_count = 0
        page_rows.append({
            "page": page,
            "section": source_page["section"],
            "validation_mode": validation_mode,
            "principle_ids": list(source_page["principle_ids"]),
            "ocr_line_count": len(source_page.get("ocr_lines") or ()),
            "compile_count": compile_count,
            "hard_pass": page_pass,
        })
        if not page_pass:
            issues.append(f"page:{page}:failed")

    if not corpus["hard_pass"]:
        issues.extend(f"corpus:{item}" for item in corpus["issues"])
    if not base_volume["hard_pass"]:
        issues.extend(f"base_volume:{item}" for item in base_volume["issues"])
    return {
        "schema_version": "arr.maas.book_page_audit.v1",
        "hard_pass": not issues,
        "issues": issues,
        "page_count": len(page_rows),
        "principle_count": len(principle_rows),
        "recursive_compile_count": sum(
            int(row["compile_count"]) for row in principle_rows
        ),
        "base_volume_compile_count": len(base_volume["rows"]),
        "total_compile_count": (
            sum(int(row["compile_count"]) for row in principle_rows)
            + len(base_volume["rows"])
        ),
        "corpus": corpus,
        "base_volume": base_volume,
        "pages": page_rows,
        "principles": principle_rows,
        "_representative": representative,
    }


def render_book_advanced_principle_audit(output_path: str | Path) -> Path:
    """Render every combination, aggregation and case-study sentence."""

    audit = audit_book_pages()
    representative = audit.pop("_representative")
    rows = [row for row in audit["principles"] if row["kind"] != "base_operative"]
    columns, cell_width, cell_height = 4, 420, 238
    row_count = (len(rows) + columns - 1) // columns
    board = Image.new("RGB", (columns * cell_width, 50 + row_count * cell_height), "#e8edf4")
    draw = ImageDraw.Draw(board)
    draw.text(
        (16, 15),
        "BOOK COMBINATIONS / AGGREGATIONS / CASES - v01 long, v06 short, v11 vertical",
        fill="#111827",
    )
    with TemporaryDirectory() as temporary_directory:
        temporary = Path(temporary_directory)
        for index, row in enumerate(rows):
            x = (index % columns) * cell_width
            y = 50 + (index // columns) * cell_height
            page = ",".join(str(value) for value in row["pages"])
            title = f"p.{page} {row['kind']}  {row['label']}"
            draw.text((x + 10, y + 8), title[:58], fill="#111827")
            for orientation_index, orientation in enumerate(BOOK_ORIENTATIONS):
                compilation = representative[(row["principle_id"], orientation)]
                preview = temporary / f"{index:02d}_{orientation_index}.png"
                render_compilation_preview(compilation, preview, title=title)
                with Image.open(preview) as image:
                    panel = image.crop((6, 6, 444, 319)).resize((128, 174))
                    board.paste(panel, (x + 8 + orientation_index * 136, y + 29))
                draw.text(
                    (x + 11 + orientation_index * 136, y + 207),
                    orientation.replace("_axis", ""),
                    fill="#4b5563",
                )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output.with_suffix(".tmp.png")
    board.save(temporary_output)
    temporary_output.replace(output)
    return output


__all__ = ["audit_book_pages", "render_book_advanced_principle_audit"]
