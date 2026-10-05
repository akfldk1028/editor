"""Bounded read model for the large append-only MAAS outcome graph."""

from __future__ import annotations

from backend.app.modules.design.generation import paths as _design_paths

from collections import defaultdict, deque
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "arr.maas.outcome_graph_slice.v1"


def default_outcome_graph_path(pnu: str) -> Path:
    configured_dir = os.getenv("MAAS_OUTCOME_GRAPH_DIR", "").strip()
    base_dir = (
        Path(configured_dir).resolve()
        if configured_dir
        else _design_paths.workspace_root()
        / "docs"
        / "ai-session-memory"
        / "maas-cache"
        / "outcome-graphs"
    )
    safe_pnu = "".join(char for char in str(pnu) if char.isalnum() or char in "-_")
    safe_pnu = safe_pnu or hashlib.sha256(str(pnu).encode("utf-8")).hexdigest()[:20]
    return base_dir / f"pnu-{safe_pnu}.json"


@lru_cache(maxsize=2)
def _load_payload(path_text: str, modified_ns: int) -> dict[str, Any]:
    del modified_ns
    path = Path(path_text)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("outcome graph payload must be an object")
    return payload


def _compact_attributes(kind: str, attributes: dict[str, Any]) -> dict[str, Any]:
    common = (
        "candidate_id", "program_slug", "selected", "stage", "status",
        "geometry_hash", "projected_geometry_hash", "program_hash",
        "family", "name", "base_seed", "book_principle_id", "book_scope",
        "source_seed", "geometry_family", "legal_fit_strength", "program_hard_pass",
        "legal_hard_pass", "parking_hard_pass", "combined_hard_pass",
        "final_book_vlm_hard_pass", "final_book_vlm_actions", "vlm_critic_score",
        "visible_family_count", "dominant_family_share", "failure_reasons",
        "image_path", "image_uri", "render_path", "source_id", "title",
        "visible_form_traits", "authority", "chassis_family", "operator_path",
    )
    result = {key: attributes.get(key) for key in common if key in attributes}
    if "book_scope" in result:
        result["base_model"] = result.pop("book_scope")
    if kind in {"geometry_program", "projected_geometry_program", "book_base_geometry"}:
        typed = attributes.get("typed_ast")
        if isinstance(typed, dict):
            result["typed_ast_summary"] = {
                "name": typed.get("name"),
                "root_id": typed.get("root_id"),
                "node_count": typed.get("node_count"),
            }
    return result


def _compact_node(node: dict[str, Any]) -> dict[str, Any]:
    kind = str(node.get("kind") or node.get("type") or "unknown")
    attributes = node.get("attributes") if isinstance(node.get("attributes"), dict) else {}
    label = (
        attributes.get("candidate_id")
        or attributes.get("name")
        or attributes.get("title")
        or attributes.get("book_principle_id")
        or attributes.get("program_slug")
        or kind.replace("_", " ").title()
    )
    if kind == "book_scope":
        kind = "book_base_model"
        label = f"{label} Base Model"
    compact_attributes = _compact_attributes(kind, attributes)
    if kind == "compiled_geometry" and not compact_attributes.get("geometry_hash"):
        compact_attributes["geometry_hash"] = str(
            attributes.get("geometry_hash") or node.get("identity") or ""
        )
    return {
        "id": str(node.get("id") or ""),
        "kind": kind,
        "label": str(label),
        "attributes": compact_attributes,
    }


def build_outcome_graph_slice(
    *,
    pnu: str,
    graph_path: str | Path | None = None,
    node_id: str = "",
    candidate_id: str = "",
    geometry_hash: str = "",
    depth: int = 3,
    max_nodes: int = 180,
) -> dict[str, Any]:
    # A selected archive run owns its causal shard. Falling back to the
    # historical PNU graph is retained for callers that do not select a run.
    path = Path(graph_path).resolve() if graph_path else default_outcome_graph_path(pnu)
    if not path.exists():
        return {
            "schema_version": SCHEMA_VERSION,
            "pnu": str(pnu),
            "status": "not_found",
            "path": str(path),
            "nodes": [],
            "edges": [],
            "root_node_ids": [],
        }
    stat = path.stat()
    payload = _load_payload(str(path.resolve()), stat.st_mtime_ns)
    raw_nodes = [item for item in payload.get("nodes") or () if isinstance(item, dict) and item.get("id")]
    raw_edges = [item for item in payload.get("edges") or () if isinstance(item, dict)]
    nodes_by_id = {str(item["id"]): item for item in raw_nodes}

    roots: list[str] = []
    if node_id and node_id in nodes_by_id:
        roots = [node_id]
    elif geometry_hash:
        for item in raw_nodes:
            attributes = item.get("attributes") if isinstance(item.get("attributes"), dict) else {}
            values = {
                str(item.get("identity") or ""),
                str(attributes.get("geometry_hash") or ""),
                str(attributes.get("projected_geometry_hash") or ""),
            }
            if geometry_hash in values:
                roots.append(str(item["id"]))
                break
    elif candidate_id:
        for item in raw_nodes:
            attributes = item.get("attributes") if isinstance(item.get("attributes"), dict) else {}
            values = {
                str(item.get("id") or ""), str(item.get("identity") or ""),
                str(attributes.get("candidate_id") or ""), str(attributes.get("id") or ""),
            }
            if candidate_id in values:
                roots.append(str(item["id"]))
                break
    if not roots:
        roots = [
            str(item["id"]) for item in raw_nodes
            if str(item.get("kind") or "") == "geometry_portfolio"
        ][-1:]
    if not roots:
        selected_outcomes = [
            str(item["id"]) for item in raw_nodes
            if str(item.get("kind") or "") == "outcome"
            and bool((item.get("attributes") or {}).get("selected"))
        ]
        if selected_outcomes:
            selected_set = set(selected_outcomes)
            degree = defaultdict(int)
            for edge in raw_edges:
                source = str(edge.get("source") or "")
                target = str(edge.get("target") or "")
                if source in selected_set:
                    degree[source] += 1
                if target in selected_set:
                    degree[target] += 1
            roots = [max(selected_outcomes, key=lambda item: degree[item])]
    if not roots:
        roots = [
            str(item["id"]) for item in raw_nodes
            if str(item.get("kind") or "") in {"geometry_portfolio", "vlm_portfolio_critic"}
        ][-1:]

    incoming: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    outgoing: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for edge in raw_edges:
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if source not in nodes_by_id or target not in nodes_by_id:
            continue
        outgoing[source].append((target, edge))
        incoming[target].append((source, edge))

    bounded_depth = max(1, min(5, int(depth)))
    bounded_max_nodes = max(20, min(400, int(max_nodes)))
    visited = set(roots)
    # Keep the slice a lineage, not a sibling explosion: ancestors are followed
    # only backwards and descendants only forwards from the selected outcome.
    queue = deque(
        (root, 0, direction)
        for root in roots
        for direction in ("incoming", "outgoing")
    )
    while queue and len(visited) < bounded_max_nodes:
        current, level, direction = queue.popleft()
        if level >= bounded_depth:
            continue
        neighbors = incoming.get(current, ()) if direction == "incoming" else outgoing.get(current, ())
        for neighbor, _edge_record in neighbors:
            if neighbor in visited:
                continue
            visited.add(neighbor)
            queue.append((neighbor, level + 1, direction))
            if len(visited) >= bounded_max_nodes:
                break

    selected_edges = [
        {
            "id": str(edge.get("id") or ""),
            "source": str(edge.get("source") or ""),
            "target": str(edge.get("target") or ""),
            "kind": str(edge.get("kind") or edge.get("relation") or "related_to"),
        }
        for edge in raw_edges
        if str(edge.get("source") or "") in visited
        and str(edge.get("target") or "") in visited
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "source_schema_version": str(payload.get("schema_version") or ""),
        "pnu": str(pnu),
        "status": "ready",
        "path": str(path),
        "root_node_ids": roots,
        "nodes": [_compact_node(nodes_by_id[item]) for item in visited if item in nodes_by_id],
        "edges": selected_edges,
        "counts": {
            "source_node_count": len(raw_nodes),
            "source_edge_count": len(raw_edges),
            "slice_node_count": len(visited),
            "slice_edge_count": len(selected_edges),
        },
        "contracts": {
            "bounded_read_model": True,
            "full_typed_ast_omitted": True,
            "frontend_must_not_synthesize_edges": True,
        },
    }


__all__ = ["SCHEMA_VERSION", "build_outcome_graph_slice", "default_outcome_graph_path"]
