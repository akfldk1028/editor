"""Token-bounded causal passport view consumed by geometry agents."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from backend.app.modules.design.generation.maas.preference.paper_sources import executable_paper_method_context


SCHEMA_VERSION = "arr.maas.mass_execution_agent_context.v1"


def build_mass_execution_agent_context(
    passport: Mapping[str, Any],
    *,
    geometry_graph_snapshot: Mapping[str, Any] | None = None,
    maximum_active_nodes: int = 48,
) -> dict[str, Any]:
    """Expose failures and editable causal IDs without dumping the UI graph."""

    stages = [row for row in passport.get("stages") or () if isinstance(row, dict)]
    graph = passport.get("activation_graph") if isinstance(passport.get("activation_graph"), dict) else {}
    nodes = [row for row in graph.get("nodes") or () if isinstance(row, dict)]
    edges = [row for row in graph.get("edges") or () if isinstance(row, dict)]
    active_nodes = [row for row in nodes if float(row.get("activation") or 0.0) > 0.0]
    active_ids = {str(row.get("id") or "") for row in active_nodes}
    failed = [row for row in stages if row.get("status") == "failed"]
    pending = [row for row in stages if row.get("required_for_final") and row.get("status") == "not_evaluated"]
    vlm = next((row for row in stages if row.get("id") == "vlm"), {})
    snapshot = dict(geometry_graph_snapshot or {})
    edit_contract = snapshot.get("agent_edit_contract") if isinstance(snapshot.get("agent_edit_contract"), dict) else {}
    protected = {str(value) for value in edit_contract.get("protected_geometry_node_ids") or ()}
    editable_ast_nodes = [
        {
            "node_id": str(row.get("source_id") or ""),
            "operator": str(row.get("operator") or ""),
            "kind": str(row.get("kind") or ""),
            "semantic_role": str(row.get("semantic_role") or ""),
            "status": str(row.get("status") or ""),
        }
        for row in active_nodes
        if str(row.get("id") or "").startswith("ast:")
        and row.get("source_id")
        and str(row.get("source_id")) not in protected
    ]
    reference_images = [
        {
            "node_id": str(row.get("id") or ""),
            "source_id": str(row.get("source_id") or ""),
            "title": str(row.get("label") or ""),
            "source": str((row.get("evidence") or {}).get("source") or ""),
            "source_url": str((row.get("evidence") or {}).get("source_url") or ""),
            "image_url": str((row.get("evidence") or {}).get("image_url") or ""),
            "preview_url": str((row.get("evidence") or {}).get("preview_url") or ""),
            "local_path": str((row.get("evidence") or {}).get("local_path") or ""),
            "sha256": str((row.get("evidence") or {}).get("sha256") or ""),
            "selection_role": str((row.get("evidence") or {}).get("selection_role") or ""),
            "matched_tags": list((row.get("evidence") or {}).get("matched_tags") or ()),
            "vlm_assessment": deepcopy((row.get("evidence") or {}).get("vlm_assessment") or {}),
        }
        for row in active_nodes
        if row.get("kind") == "vlm_reference_image"
    ]
    stage_status = {
        str(row.get("id") or ""): str(row.get("status") or "")
        for row in stages
    }
    typed_geometry_edits = deepcopy((vlm.get("evidence") or {}).get("geometry_edits") or [])
    paper_method_context = executable_paper_method_context(
        operators=tuple(
            str(row.get("operator") or "")
            for row in active_nodes
            if str(row.get("id") or "").startswith("ast:")
        ),
        stage_status=stage_status,
        structural_hash=str(passport.get("structural_hash") or ""),
        typed_geometry_edit_count=len(typed_geometry_edits),
        semantic_role_count=sum(
            bool(str(row.get("semantic_role") or ""))
            for row in active_nodes
            if str(row.get("id") or "").startswith("ast:")
        ),
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "purpose": "causal_observation_for_author_critic_repair_selector",
        "program_hash": str(passport.get("program_hash") or ""),
        "geometry_hash": str(passport.get("geometry_hash") or ""),
        "passport_status": str(passport.get("status") or ""),
        "stage_status": stage_status,
        "failed_stages": [
            {"id": str(row.get("id") or ""), "evidence": deepcopy(row.get("evidence") or {})}
            for row in failed
        ],
        "pending_required_stages": [str(row.get("id") or "") for row in pending],
        "active_nodes": [
            {
                "id": str(row.get("id") or ""),
                "source_id": str(row.get("source_id") or ""),
                "column": str(row.get("column") or ""),
                "label": str(row.get("label") or ""),
                "operator": str(row.get("operator") or ""),
                "activation": round(float(row.get("activation") or 0.0), 4),
            }
            for row in active_nodes[:max(1, int(maximum_active_nodes))]
        ],
        "active_edges": [
            {
                "source": str(row.get("source") or ""),
                "target": str(row.get("target") or ""),
                "relation": str(row.get("relation") or ""),
                "activation": round(float(row.get("activation") or 0.0), 4),
            }
            for row in edges
            if float(row.get("activation") or 0.0) > 0.0
            and str(row.get("source") or "") in active_ids
            and str(row.get("target") or "") in active_ids
        ][:96],
        "editable_ast_nodes": editable_ast_nodes[:96],
        "protected_ast_node_ids": sorted(protected),
        "vlm_reference_images": reference_images[:8],
        "vlm_concept_scores": deepcopy((vlm.get("evidence") or {}).get("concept_scores") or {}),
        "typed_geometry_edits": typed_geometry_edits,
        "research_method_context": paper_method_context,
        "agent_rules": [
            "Treat this as observed execution evidence, never as hidden-neuron data.",
            "Target only exact editable AST node IDs also present in the current geometry graph contract.",
            "Repair failed stages; do not infer a pass from a pending stage.",
            "Recompile, rerender and rerun hard gates after every typed edit.",
        ],
    }


__all__ = ["SCHEMA_VERSION", "build_mass_execution_agent_context"]
