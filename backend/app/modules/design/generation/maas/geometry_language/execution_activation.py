"""Build the observable causal graph for one MASS execution passport."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from typing import Any, Mapping

from backend.app.modules.design.generation.maas.geometry_language.execution_evidence import status_activation


def build_activation_graph(
    *,
    program: Any,
    ordered_nodes: tuple[Any, ...],
    trace_by_id: Mapping[str, Any],
    stages: list[dict[str, Any]],
    preview: Mapping[str, Any],
    vlm: Mapping[str, Any],
    gate_issues: tuple[Any, ...],
    agent_collaboration: Mapping[str, Any] | None = None,
    geometry_hash: str = "",
    elevation_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    stage_by_id = {row["id"]: row for row in stages}
    for node in ordered_nodes:
        source = str((node.provenance or {}).get("source") or "")
        column = (
            "book" if source == "book_recursive_projection"
            else "program" if source in {"post_book_program_projection", "program_projection_connectivity_guard"}
            else "base" if node.kind == "primitive" or node.semantic_role == "base_seed"
            else "geometry"
        )
        evaluated = node.id in trace_by_id
        nodes.append({
            "id": f"ast:{node.id}",
            "source_id": node.id,
            "column": column,
            "label": str((node.provenance or {}).get("book_verb") or node.operator),
            "kind": node.kind,
            "operator": node.operator,
            "semantic_role": str(node.semantic_role or ""),
            "status": "evaluated" if evaluated else "failed",
            "activation": 1.0 if evaluated else 0.0,
            "evidence": deepcopy(trace_by_id.get(node.id) or {}),
        })
        for input_id in node.inputs:
            edges.append(edge(f"ast:{input_id}", f"ast:{node.id}", "solid_input", 1.0 if evaluated else 0.0))

    program_stage = stage_by_id["program"]
    nodes.append(flow_node("flow:program", "program", program_stage["label"], program_stage["status"], evidence=program_stage["evidence"]))
    if ordered_nodes:
        edges.append(edge(f"ast:{program.root_id}", "flow:program", "program_projection_result", status_activation(program_stage["status"])))
    compiler_status = stage_by_id["compiler"]["status"]
    nodes.append(flow_node("flow:compiler", "compiler", "Geometry Compiler", compiler_status))
    edges.append(edge("flow:program", "flow:compiler", "compile", 1.0 if compiler_status == "passed" else 0.0))
    gate_status = stage_by_id["geometry_gate"]["status"]
    nodes.append(flow_node("flow:geometry_gate", "gate", "Geometry GATE", gate_status, evidence={"issues": [issue.to_dict() for issue in gate_issues]}))
    edges.append(edge("flow:compiler", "flow:geometry_gate", "validate", 1.0 if gate_status == "passed" else 0.0))

    prior = "flow:geometry_gate"
    for stage_id in ("site", "capacity", "law", "parking", "program_fit"):
        row = stage_by_id[stage_id]
        node_id = f"flow:{stage_id}"
        nodes.append(flow_node(node_id, stage_id, row["label"], row["status"], evidence=row["evidence"]))
        edges.append(edge(prior, node_id, "downstream_gate", status_activation(row["status"])))
        prior = node_id

    render_status = stage_by_id["render"]["status"]
    nodes.append(flow_node("flow:render", "render", "4-view render", render_status, evidence=preview))
    edges.append(edge("flow:compiler", "flow:render", "render", status_activation(render_status)))
    for view in preview.get("views") or ("isometric", "opposite", "front", "top"):
        view_id = f"render:{view}"
        nodes.append(flow_node(view_id, "render", str(view), render_status))
        edges.append(edge("flow:render", view_id, "view", status_activation(render_status)))
    nodes.append({
        "id": "render:mass_png",
        "column": "render",
        "label": "Generated MASS PNG",
        "kind": "mass_render_result",
        "status": render_status,
        "activation": status_activation(render_status),
        "evidence": deepcopy(dict(preview)),
    })
    edges.append(edge("flow:render", "render:mass_png", "materialized_png", status_activation(render_status)))

    vlm_status = str(vlm.get("status") or "not_evaluated")
    nodes.append(flow_node("flow:vlm", "vlm", "VLM critic", vlm_status, evidence=vlm))
    for view in preview.get("views") or ("isometric", "opposite", "front", "top"):
        edges.append(edge(f"render:{view}", "flow:vlm", "visual_input", status_activation(vlm_status)))
    edges.append(edge("render:mass_png", "flow:vlm", "candidate_image_input", status_activation(vlm_status)))
    append_vlm_nodes(nodes, edges, vlm)

    selector = stage_by_id["selector"]
    nodes.append(flow_node("flow:selector", "selector", selector["label"], selector["status"], evidence=selector["evidence"]))
    edges.append(edge(prior, "flow:selector", "hard_gate_input", status_activation(selector["status"])))
    edges.append(edge("flow:vlm", "flow:selector", "critic_input", status_activation(vlm_status)))
    append_agent_collaboration_nodes(nodes, edges, agent_collaboration or {})
    nodes.append({
        "id": "result:mass",
        "column": "result",
        "label": str(getattr(program, "name", "") or "Generated MASS"),
        "kind": "mass_result",
        "status": render_status,
        "activation": status_activation(render_status),
        "evidence": deepcopy(dict(preview)),
    })
    edges.append(edge("render:mass_png", "result:mass", "generated_result", status_activation(render_status)))
    edges.append(edge(
        "flow:selector",
        "result:mass",
        "selection_status",
        1.0 if agent_collaboration else status_activation(selector["status"]),
    ))
    elevation = deepcopy(dict(elevation_evidence or {}))
    elevation_views = [
        dict(row) for row in elevation.get("views") or ()
        if isinstance(row, Mapping)
    ]
    elevation_generated = (
        str(elevation.get("status") or "") == "generated"
        and len(elevation_views) == 6
    )
    elevation_status = (
        "generated"
        if elevation_generated
        else str(elevation.get("status") or "not_evaluated")
    )
    elevation_activation = 1.0 if elevation_generated else 0.0
    elevation_identity = {
        "program_hash": _safe_program_hash(program),
        "geometry_hash": str(geometry_hash or ""),
        "mass_result_node_id": "result:mass",
    }
    first_elevation_view = next(
        (row for row in elevation_views if row.get("view") == "front"),
        elevation_views[0] if elevation_views else {},
    )
    image_proposal = elevation.get("image_proposal")
    image_proposal = (
        deepcopy(dict(image_proposal))
        if isinstance(image_proposal, Mapping)
        else {}
    )
    image_status = str(image_proposal.get("status") or "not_evaluated")
    image_activation = 1.0 if image_status == "complete" else 0.0
    proposal_artifact = image_proposal.get("artifact")
    proposal_artifact = (
        deepcopy(dict(proposal_artifact))
        if isinstance(proposal_artifact, Mapping)
        else {}
    )
    nodes.extend((
        {
            "id": "elevation:mesh_handoff",
            "column": "elevation_handoff",
            "label": f"Elevation mesh handoff · {elevation_status}",
            "kind": "elevation_mesh_handoff",
            "status": elevation_status,
            "activation": elevation_activation,
            "evidence": {
                **elevation_identity,
                "artifact_exists": elevation_generated,
                "manifest_path": str(elevation.get("manifest_path") or ""),
                "required_payload": ["indexed_mesh", "stable_face_ids", "camera_contract"],
            },
        },
        {
            "id": "elevation:condition_pack",
            "column": "elevation_condition",
            "label": f"Elevation condition pack · {elevation_status}",
            "kind": "elevation_condition_pack",
            "status": elevation_status,
            "activation": elevation_activation,
            "evidence": {
                **elevation_identity,
                "artifact_exists": elevation_generated,
                "condition_pack_path": str(elevation.get("condition_pack_path") or ""),
                "required_layers": ["silhouette", "metric_depth", "surface_normals", "floor_guides", "facade_planes"],
            },
        },
        {
            "id": "elevation:result",
            "column": "elevation_result",
            "label": f"Generated elevation · {len(elevation_views)} views",
            "kind": "elevation_result",
            "status": elevation_status,
            "activation": elevation_activation,
            "evidence": {
                **elevation_identity,
                "artifact_exists": elevation_generated,
                "view_count": len(elevation_views),
                "views": elevation_views,
                "preview_url": str(first_elevation_view.get("preview_url") or ""),
                "truth": "deterministic projections of the compiled indexed MASS mesh",
            },
        },
        {
            "id": "elevation:image_agent",
            "column": "elevation_image_agent",
            "label": f"Architectural Render Agent · {image_status}",
            "kind": "elevation_image_agent",
            "status": image_status,
            "activation": image_activation,
            "evidence": {
                **elevation_identity,
                "provider": str(image_proposal.get("provider") or ""),
                "provider_metadata": deepcopy(
                    dict(image_proposal.get("provider_metadata") or {})
                ),
                "request_count": int(image_proposal.get("request_count") or 0),
                "retry_count": int(image_proposal.get("retry_count") or 0),
                "presentation": deepcopy(
                    dict(image_proposal.get("presentation") or {})
                ),
                "strategy": deepcopy(dict(image_proposal.get("strategy") or {})),
                "issues": deepcopy(list(image_proposal.get("issues") or ())),
            },
        },
        {
            "id": "elevation:proposal",
            "column": "elevation_proposal",
            "label": f"Render ALT 01 · {image_status}",
            "kind": "elevation_image_proposal",
            "status": image_status,
            "activation": image_activation,
            "evidence": {
                **elevation_identity,
                "artifact_exists": bool(proposal_artifact.get("path")),
                "artifact": proposal_artifact,
                "preview_url": str(proposal_artifact.get("preview_url") or ""),
                "manifest_path": str(image_proposal.get("manifest_path") or ""),
                "geometry_mutation_allowed": False,
                "presentation": deepcopy(
                    dict(image_proposal.get("presentation") or {})
                ),
            },
        },
    ))
    edges.extend((
        edge("result:mass", "elevation:mesh_handoff", "requests_elevation_handoff", elevation_activation),
        edge("elevation:mesh_handoff", "elevation:condition_pack", "builds_condition_pack", elevation_activation),
        edge("elevation:condition_pack", "elevation:result", "generates_elevation", elevation_activation),
        edge("elevation:condition_pack", "elevation:image_agent", "requests_facade_proposal", image_activation),
        edge("elevation:image_agent", "elevation:proposal", "generates_facade_proposal", image_activation),
    ))
    ast_node_ids = [f"ast:{node.id}" for node in ordered_nodes]
    incoming_ast_targets = {
        str(item.get("target") or "")
        for item in edges
        if str(item.get("target") or "").startswith("ast:")
    }
    root_node_ids = [node_id for node_id in ast_node_ids if node_id not in incoming_ast_targets]
    try:
        program_hash = str(program.program_hash())
    except (AttributeError, TypeError, ValueError):
        program_hash = ""
    return {
        "schema_version": "arr.maas.mass_activation_graph.v1",
        "graph_id": f"mass-execution:{program_hash or program.root_id}",
        "internal_neuron_claim": False,
        "causal_program_trace": True,
        "root_node_ids": root_node_ids,
        "result_node_ids": ["result:mass"],
        "query_contract": {
            "selection_unit": "one_executed_mass",
            "default_query": "active_ancestors_of_result:mass",
            "node_identity": "stable node.id within program_hash",
            "edge_direction": "cause_to_effect",
            "active_edge_predicate": "activation > 0",
            "inactive_evidence_policy": "retain node and edge with activation=0; never infer pass",
            "visualization_policy": "render one selected MASS induced subgraph; never create parallel authority graphs",
            "book_image_policy": "BOOK is typed language provenance, not raster image evidence",
            "vlm_image_policy": "materialize only images actually submitted to a recorded VLM evaluation",
        },
        "nodes": nodes,
        "edges": edges,
    }


def refresh_elevation_proposal_graph(
    graph: dict[str, Any],
    proposal: Mapping[str, Any],
) -> dict[str, Any]:
    """Refresh the proposal nodes after an explicit post-MASS image call."""

    result = deepcopy(graph)
    nodes = result.get("nodes")
    edges = result.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ValueError("invalid MASS activation graph")
    node_map = {
        str(node.get("id") or ""): node
        for node in nodes
        if isinstance(node, dict)
    }
    image_node = node_map.get("elevation:image_agent")
    proposal_node = node_map.get("elevation:proposal")
    if image_node is None or proposal_node is None:
        raise ValueError("MASS graph does not contain elevation proposal nodes")
    status = str(proposal.get("status") or "failed")
    activation = 1.0 if status == "complete" else 0.0
    identity = deepcopy(dict(proposal.get("identity") or {}))
    artifact = deepcopy(dict(proposal.get("artifact") or {}))
    image_node.update({
        "label": f"Architectural Render Agent · {status}",
        "status": status,
        "activation": activation,
        "evidence": {
            **identity,
            "mass_result_node_id": "result:mass",
            "provider": str(proposal.get("provider") or ""),
            "provider_metadata": deepcopy(
                dict(proposal.get("provider_metadata") or {})
            ),
            "request_count": int(proposal.get("request_count") or 0),
            "retry_count": int(proposal.get("retry_count") or 0),
            "presentation": deepcopy(
                dict(proposal.get("presentation") or {})
            ),
            "strategy": deepcopy(dict(proposal.get("strategy") or {})),
            "issues": deepcopy(list(proposal.get("issues") or ())),
        },
    })
    proposal_node.update({
        "label": f"Render ALT 01 · {status}",
        "status": status,
        "activation": activation,
        "evidence": {
            **identity,
            "mass_result_node_id": "result:mass",
            "artifact_exists": bool(artifact.get("path")),
            "artifact": artifact,
            "preview_url": str(artifact.get("preview_url") or ""),
            "manifest_path": str(proposal.get("manifest_path") or ""),
            "geometry_mutation_allowed": False,
            "presentation": deepcopy(
                dict(proposal.get("presentation") or {})
            ),
        },
    })
    for item in edges:
        if (
            isinstance(item, dict)
            and item.get("relation") in {
                "requests_facade_proposal",
                "generates_facade_proposal",
            }
        ):
            item["activation"] = activation
    return result


def refresh_multi_view_elevation_graph(
    graph: dict[str, Any],
    proposal: Mapping[str, Any],
) -> dict[str, Any]:
    """Materialize multi-view generation and gates in the existing MASS graph."""

    result = deepcopy(graph)
    nodes = result.get("nodes")
    edges = result.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ValueError("invalid MASS activation graph")
    node_ids = {
        "elevation:multi_view_generator",
        "elevation:multi_view_gate",
        "elevation:multi_view_critic",
        "elevation:multi_view_proposal",
    }
    relations = {
        "requests_multi_view_facades",
        "validates_multi_view_elevation",
        "requests_joint_elevation_critic",
        "accepts_multi_view_elevation",
    }
    nodes[:] = [
        node
        for node in nodes
        if not isinstance(node, dict) or str(node.get("id") or "") not in node_ids
    ]
    edges[:] = [
        item
        for item in edges
        if not isinstance(item, dict)
        or str(item.get("relation") or "") not in relations
    ]
    status = str(proposal.get("status") or "failed")
    accepted = status == "accepted"
    identity = deepcopy(dict(proposal.get("identity") or {}))
    artifacts = deepcopy(dict(proposal.get("artifacts") or {}))
    gate = deepcopy(dict(proposal.get("deterministic_gate") or {}))
    critic = deepcopy(dict(proposal.get("critic") or {}))
    generator_active = 1.0 if artifacts else 0.0
    gate_active = 1.0 if gate.get("status") == "passed" else 0.0
    critic_active = 1.0 if critic.get("status") == "passed" else 0.0
    accepted_active = 1.0 if accepted else 0.0
    nodes.extend([
        {
            "id": "elevation:multi_view_generator",
            "column": "elevation_image_agent",
            "label": f"4-Facade Generator · {status}",
            "kind": "elevation_multi_view_generator",
            "status": "generated" if artifacts else "failed",
            "activation": generator_active,
            "evidence": {
                **identity,
                "artifacts": artifacts,
                "paid_request_attempt_count": int(
                    proposal.get("image_paid_request_attempt_count") or 0
                ),
                "repair_count_by_view": deepcopy(
                    dict(proposal.get("repair_count_by_view") or {})
                ),
                "retry_count": int(proposal.get("retry_count") or 0),
            },
        },
        {
            "id": "elevation:multi_view_gate",
            "column": "elevation_condition",
            "label": f"Multi-View Deterministic GATE · {gate.get('status') or 'not_evaluated'}",
            "kind": "elevation_multi_view_gate",
            "status": str(gate.get("status") or "not_evaluated"),
            "activation": gate_active,
            "evidence": gate,
        },
        {
            "id": "elevation:multi_view_critic",
            "column": "elevation_image_agent",
            "label": f"Joint 4-View Critic · {critic.get('status') or 'not_evaluated'}",
            "kind": "elevation_multi_view_critic",
            "status": str(critic.get("status") or "not_evaluated"),
            "activation": critic_active,
            "evidence": critic,
        },
        {
            "id": "elevation:multi_view_proposal",
            "column": "elevation_proposal",
            "label": f"Multi-View ALT 01 · {status}",
            "kind": "elevation_multi_view_proposal",
            "status": status,
            "activation": accepted_active,
            "evidence": {
                **identity,
                "artifacts": artifacts,
                "montage": deepcopy(dict(proposal.get("montage") or {})),
                "manifest_path": str(proposal.get("manifest_path") or ""),
                "paid_request_attempt_count": int(
                    proposal.get("paid_request_attempt_count") or 0
                ),
                "geometry_mutation_allowed": False,
            },
        },
    ])
    edges.extend([
        edge(
            "elevation:condition_pack",
            "elevation:multi_view_generator",
            "requests_multi_view_facades",
            generator_active,
        ),
        edge(
            "elevation:multi_view_generator",
            "elevation:multi_view_gate",
            "validates_multi_view_elevation",
            gate_active,
        ),
        edge(
            "elevation:multi_view_gate",
            "elevation:multi_view_critic",
            "requests_joint_elevation_critic",
            critic_active,
        ),
        edge(
            "elevation:multi_view_critic",
            "elevation:multi_view_proposal",
            "accepts_multi_view_elevation",
            accepted_active,
        ),
    ])
    return result


def _safe_program_hash(program: Any) -> str:
    try:
        return str(program.program_hash())
    except (AttributeError, TypeError, ValueError):
        return ""


def append_agent_collaboration_nodes(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    collaboration: Mapping[str, Any],
) -> None:
    if not collaboration:
        return
    identity = collaboration.get("identity")
    identity = dict(identity) if isinstance(identity, Mapping) else {}
    evidence_rows = [row for row in collaboration.get("evidence") or () if isinstance(row, Mapping)]
    nodes.append({
        "id": "agent:design_orchestrator",
        "column": "agent",
        "label": "Design Orchestrator",
        "kind": "specialist_agent",
        "status": "passed",
        "activation": 1.0,
        "evidence": {"identity": identity},
    })
    edges.append(edge("flow:geometry_gate", "agent:design_orchestrator", "starts_agent_review", 1.0))
    for row in evidence_rows:
        agent = str(row.get("agent") or "")
        if not agent:
            continue
        node_id = f"agent:{agent}"
        status = str(row.get("status") or "not_evaluated")
        nodes.append({
            "id": node_id,
            "column": "agent",
            "label": agent.replace("_", " ").title(),
            "kind": "specialist_agent",
            "status": status,
            "activation": status_activation(status),
            "evidence": deepcopy(dict(row)),
        })
        payload = row.get("evidence")
        payload = payload if isinstance(payload, Mapping) else {}
        if agent == "law_graph_agent":
            search = payload.get("law_search")
            search = search if isinstance(search, Mapping) else {}
            search_status = "passed" if search.get("available") else "needs_evidence"
            nodes.append({
                "id": "source:law_domain_search",
                "column": "law",
                "label": "Law domain search",
                "kind": "law_source_attempt",
                "status": search_status,
                "activation": status_activation(search_status),
                "evidence": deepcopy(dict(search)),
            })
            edges.append(edge("source:law_domain_search", node_id, "law_source_evidence", status_activation(search_status)))
            for article_id in payload.get("article_ids") or ():
                article_node_id = f"law:{article_id}"
                nodes.append({
                    "id": article_node_id,
                    "column": "law",
                    "label": str(article_id),
                    "kind": "law_article",
                    "status": "evaluated",
                    "activation": 1.0,
                    "evidence": {"article_id": str(article_id), "identity": identity},
                })
                edges.append(edge(article_node_id, node_id, "legal_citation", 1.0))
    for row in collaboration.get("handoffs") or ():
        if not isinstance(row, Mapping):
            continue
        source = str(row.get("source_agent") or "")
        target = str(row.get("target_agent") or "")
        if source and target:
            # The edge means the handoff actually occurred, not that the target
            # passed. A needs-evidence result remains visible and typed on the
            # target node while the causal transfer itself stays active.
            edges.append(edge(f"agent:{source}", f"agent:{target}", "agent_handoff", 1.0))
    if any(str(row.get("agent") or "") == "selector" for row in evidence_rows):
        edges.append(edge("agent:selector", "flow:selector", "agent_selection_decision", 1.0))


def append_vlm_nodes(nodes: list[dict[str, Any]], edges: list[dict[str, Any]], vlm: Mapping[str, Any]) -> None:
    existing = {str(node.get("id") or "") for node in nodes}
    image_inputs = vlm.get("image_inputs") if isinstance(vlm.get("image_inputs"), dict) else {}
    assessments = {
        str(item.get("source_id") or ""): item
        for item in vlm.get("reference_assessments") or ()
        if isinstance(item, dict) and item.get("source_id")
    }
    for index, reference in enumerate(image_inputs.get("references") or (), start=1):
        if not isinstance(reference, dict) or reference.get("used_by_vlm") is not True:
            continue
        source_id = str(reference.get("source_id") or index)
        digest = hashlib.sha256(source_id.encode("utf-8")).hexdigest()[:12]
        node_id = f"vlm:reference:{digest}"
        if node_id in existing:
            continue
        evidence = deepcopy(reference)
        if source_id in assessments:
            evidence["vlm_assessment"] = deepcopy(assessments[source_id])
        nodes.append({
            "id": node_id,
            "source_id": source_id,
            "column": "reference",
            "label": str(reference.get("title") or source_id or f"Reference {index}"),
            "kind": "vlm_reference_image",
            "status": "evaluated",
            "activation": 1.0,
            "evidence": evidence,
        })
        edges.append(edge(node_id, "flow:vlm", "visual_reference_input", 1.0))
        existing.add(node_id)
    for key, value in sorted((vlm.get("concept_scores") or {}).items()):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        score = max(0.0, min(1.0, float(value)))
        node_id = f"vlm:concept:{key}"
        if node_id in existing:
            continue
        nodes.append({"id": node_id, "column": "vlm", "label": str(key), "kind": "vlm_concept_score", "status": "evaluated", "activation": score, "evidence": {"score": float(value)}})
        edges.append(edge("flow:vlm", node_id, "concept_score", score))
        existing.add(node_id)
    for index, edit in enumerate(vlm.get("geometry_edits") or (), start=1):
        if not isinstance(edit, dict):
            continue
        node_id = f"vlm:edit:{index}"
        if node_id in existing:
            continue
        nodes.append({"id": node_id, "column": "repair", "label": str(edit.get("operation") or edit.get("op") or "typed edit"), "kind": "typed_geometry_edit", "status": "evaluated", "activation": 1.0, "evidence": deepcopy(edit)})
        edges.append(edge("flow:vlm", node_id, "requests_edit", 1.0))
        existing.add(node_id)


def flow_node(node_id: str, column: str, label: str, status: str, *, evidence: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {"id": node_id, "column": column, "label": label, "kind": "pipeline_stage", "status": status, "activation": status_activation(status), "evidence": deepcopy(dict(evidence or {}))}


def edge(source: str, target: str, relation: str, activation: float) -> dict[str, Any]:
    digest = hashlib.sha256(f"{source}|{relation}|{target}".encode("utf-8")).hexdigest()[:16]
    return {"id": f"edge:{digest}", "source": source, "target": target, "relation": relation, "activation": round(float(activation), 6)}


__all__ = [
    "append_agent_collaboration_nodes",
    "append_vlm_nodes",
    "build_activation_graph",
    "edge",
    "refresh_elevation_proposal_graph",
    "refresh_multi_view_elevation_graph",
]
