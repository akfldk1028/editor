"""Isolated compile/visual audit for the eleven early chassis priors."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from PIL import Image, ImageDraw

from backend.app.modules.design.generation.maas.geometry_language.compiler import CompilationResult, compile_geometry_program
from backend.app.modules.design.generation.maas.geometry_language.render import render_compilation_preview
from backend.app.modules.design.generation.maas.geometry_language.synthesis import synthesize_architectural_programs
from backend.app.modules.design.generation.maas.geometry_language.typology_priors import TYPOLOGY_PRIORS


def canonical_typology_programs():
    return synthesize_architectural_programs({
        "base_seeds": ["block", "slab", "bar", "tower", "profiled_prism"],
        "intent_tags": ["calm_prismatic", "distributed_wings", "carved_void", "oblique_section"],
        "typology_priors": [prior.typology_id for prior in TYPOLOGY_PRIORS],
        "candidate_count": len(TYPOLOGY_PRIORS),
        "maximum_operator_depth": 1,
        "allowed_macro_operators": sorted({prior.primary_operator for prior in TYPOLOGY_PRIORS}),
        "site_access_side": "south",
    }, building_type="typology_audit")


def audit_typology_priors() -> dict[str, Any]:
    programs = canonical_typology_programs()
    rows = []
    compilations: dict[str, CompilationResult] = {}
    by_prior = {prior.typology_id: prior for prior in TYPOLOGY_PRIORS}
    issues = []
    for program in programs:
        typology_id = str(program.metadata.get("early_typology_prior") or "")
        prior = by_prior[typology_id]
        compilation = compile_geometry_program(program)
        compilations[typology_id] = compilation
        root = program.node_map[program.root_id]
        rows.append({
            "typology_id": typology_id,
            "relation_class": prior.relation_class,
            "base_seed": str(program.metadata.get("base_seed") or ""),
            "operator": root.operator,
            "parameters": dict(root.parameters),
            "status": compilation.status,
            "component_count": int(compilation.metrics.get("component_count", 0)),
            "genus": int(compilation.metrics.get("genus", 0)),
            "geometry_hash": compilation.geometry_hash,
        })
        if compilation.status != "compiled":
            issues.append(f"compile_failed:{typology_id}")
        if int(compilation.metrics.get("component_count", 0)) != 1:
            issues.append(f"disconnected:{typology_id}")
        if str(program.metadata.get("base_seed") or "") != prior.preferred_base_seeds[0]:
            issues.append(f"noncanonical_seed:{typology_id}")
        if root.operator != prior.primary_operator:
            issues.append(f"operator_mismatch:{typology_id}")
    ids = {row["typology_id"] for row in rows}
    if ids != set(by_prior):
        issues.append("typology_coverage")
    if len({row["geometry_hash"] for row in rows}) != len(TYPOLOGY_PRIORS):
        issues.append("collapsed_geometry_hashes")
    open_court = next((row for row in rows if row["typology_id"] == "ushape"), {})
    closed_court = next((row for row in rows if row["typology_id"] == "courtyard"), {})
    if open_court.get("parameters", {}).get("open_side") == "closed":
        issues.append("ushape_not_open")
    if closed_court.get("parameters", {}).get("open_side") != "closed":
        issues.append("courtyard_not_closed")
    by_id = {row["typology_id"]: row for row in rows}
    if float(by_id.get("lshape", {}).get("parameters", {}).get("ratio", 0.0)) < 0.45:
        issues.append("lshape_not_legible")
    if by_id.get("hshape", {}).get("parameters", {}).get("layout") != "parallel":
        issues.append("hshape_not_parallel")
    if float(by_id.get("tower_podium", {}).get("parameters", {}).get("podium_scale", 1.0)) <= 1.4:
        issues.append("tower_podium_missing_podium")
    if int(by_id.get("grid", {}).get("genus", 0)) < 1:
        issues.append("grid_missing_field_voids")
    return {
        "schema_version": "arr.maas.typology_prior_audit.v1",
        "hard_pass": not issues,
        "issues": issues,
        "rows": rows,
        "_compilations": compilations,
    }


def render_typology_prior_audit(output_path: str | Path) -> Path:
    audit = audit_typology_priors()
    compilations = audit.pop("_compilations")
    columns, cell_width, cell_height = 4, 360, 285
    rows = (len(TYPOLOGY_PRIORS) + columns - 1) // columns
    board = Image.new("RGB", (columns * cell_width, rows * cell_height + 46), "#e8edf4")
    draw = ImageDraw.Draw(board)
    draw.text((16, 16), "EARLY CHASSIS PRIORS — topology before BOOK operations", fill="#111827")
    with TemporaryDirectory() as temporary_directory:
        temporary = Path(temporary_directory)
        for index, prior in enumerate(TYPOLOGY_PRIORS):
            x = (index % columns) * cell_width
            y = 46 + (index // columns) * cell_height
            result = compilations[prior.typology_id]
            preview = temporary / f"{index:02d}.png"
            render_compilation_preview(result, preview, title=prior.typology_id)
            with Image.open(preview) as image:
                panel = image.crop((6, 6, 444, 319)).resize((cell_width - 16, cell_height - 58))
                board.paste(panel, (x + 8, y + 8))
            row = next(item for item in audit["rows"] if item["typology_id"] == prior.typology_id)
            draw.text((x + 12, y + cell_height - 44), f"{prior.label} | {row['base_seed']} -> {row['operator']}", fill="#111827")
            draw.text((x + 12, y + cell_height - 25), f"components={row['component_count']}  genus={row['genus']}", fill="#4b5563")
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output.with_suffix(".tmp.png")
    board.save(temporary_output)
    temporary_output.replace(output)
    return output


__all__ = ["audit_typology_priors", "canonical_typology_programs", "render_typology_prior_audit"]
