"""Structured handoff for the BOOK language, MASS PNG and outcome graph."""

from __future__ import annotations

from backend.app.modules.design.generation import paths as _design_paths

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.modules.design.generation.maas.language_system import build_language_system_manifest


SCHEMA_VERSION = "arr.maas.language_visual_memory.v1"
MASS_VISUAL_EVIDENCE_SCHEMA_VERSION = "arr.maas.mass_visual_evidence_checkpoint.v1"


def workspace_root() -> Path:
    return _design_paths.workspace_root()


def _workspace_relative(path: Path, *, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def load_mass_visual_evidence(
    *, evidence_file: str | Path | None = None
) -> dict[str, Any]:
    """Load the small, reviewed checkpoint without parsing giant run archives."""

    root = workspace_root()
    source = (
        Path(evidence_file)
        if evidence_file
        else root / "docs" / "ai-session-memory" / "maas-latest-mass-visual-evidence.json"
    )
    source_path = _workspace_relative(source, root=root)
    if not source.is_file():
        return {
            "schema_version": MASS_VISUAL_EVIDENCE_SCHEMA_VERSION,
            "available": False,
            "source": source_path,
            "reason": "reviewed MASS visual evidence checkpoint is absent",
        }

    payload = json.loads(source.read_text(encoding="utf-8"))
    if payload.get("schema_version") != MASS_VISUAL_EVIDENCE_SCHEMA_VERSION:
        raise ValueError(
            "Unsupported MASS visual evidence schema: "
            f"{payload.get('schema_version')!r}"
        )

    completed = payload.get("latest_completed_run") or {}
    board = root / str(completed.get("board_png") or "")
    payload["available"] = bool(completed and board.is_file())
    payload["source"] = source_path
    payload["board_png_available"] = board.is_file()
    return payload


def build_language_visual_memory(
    *,
    frontend_png: str | Path | None = None,
    mass_evidence_file: str | Path | None = None,
) -> dict[str, Any]:
    root = workspace_root()
    screenshot = Path(frontend_png) if frontend_png else root / "previews" / "maas-language-flow-final.png"
    screenshot_path = _workspace_relative(screenshot, root=root)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "language_system": build_language_system_manifest(),
        "visualization": {
            "frontend_png": screenshot_path,
            "available": screenshot.is_file(),
            "role": "human-readable projection of the same typed manifest",
            "model_internal_neuron_claim": False,
        },
        "mass_png_memory_contract": {
            "schema_version": "arr.maas.mass_png_render_artifact.v1",
            "binding_fields": [
                "pnu",
                "program_slug",
                "program_hash",
                "projected_program_hash",
                "geometry_hash",
                "book_principle_id",
                "base_model",
                "capacity_alternative_id",
                "capacity_target_utilization",
                "capacity_achieved_utilization",
                "board_png",
                "card_index",
                "crop_box",
                "render_hard_pass",
                "gate_results",
                "vlm_response_id",
                "reference_ids",
            ],
            "geometry_authority": "typed_ast_plus_program_hash_plus_geometry_hash",
            "png_role": "human_and_vlm_visual_observation_not_geometry_authority",
            "write_stage": "after MASS portfolio PNG render",
            "outcome_graph_node_kind": "render_artifact",
            "outcome_graph_edges": ["projected_geometry_program rendered_as render_artifact", "render_artifact measured_by outcome"],
        },
        "latest_mass_visual_evidence": load_mass_visual_evidence(
            evidence_file=mass_evidence_file
        ),
        "execution_order": [
            "BOOK p.3 Base Model and orientation",
            "internal host proportion and relation scaffold",
            "BOOK principle and variation",
            "program projection",
            "site-derived capacity alternative projection",
            "geometry/program/legal/retention/parking hard gates",
            "MASS PNG render",
            "ArchDaily-grounded VLM critic and typed repair when explicitly enabled",
            "accepted outcome memory",
        ],
        "live_vlm_launched_by_export": False,
    }


__all__ = [
    "MASS_VISUAL_EVIDENCE_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "build_language_visual_memory",
    "load_mass_visual_evidence",
    "workspace_root",
]
