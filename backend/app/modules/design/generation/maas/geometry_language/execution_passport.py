"""Facade and orchestration for auditable per-MASS execution passports."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
from typing import Any, Mapping

from PIL import Image, UnidentifiedImageError

from backend.app.modules.design.generation.maas.mass_product_evidence import resolve_floor_capacity_plan_identity

from backend.app.modules.design.generation.maas.geometry_language.execution_activation import append_vlm_nodes, build_activation_graph
from backend.app.modules.design.generation.maas.geometry_language.execution_evidence import DOWNSTREAM_ALIASES, DOWNSTREAM_STAGE_KEYS, merge_agent_stage_evidence, normalize_downstream_evidence, passport_state, preview_evidence, stage, stage_from_downstream, status_activation, vlm_evidence
from backend.app.modules.design.generation.maas.geometry_language.execution_persistence import passport_path_for_preview, write_mass_execution_passport
from backend.app.modules.design.generation.maas.geometry_language.compiler import revalidate_compilation_mesh
from backend.app.modules.design.generation.maas.geometry_language.gate import compilation_gate


MASS_EXECUTION_PASSPORT_SCHEMA = "arr.maas.mass_execution_passport.v1"


def build_mass_execution_passport(
    compilation: Any,
    *,
    preview_path: str | Path | None = None,
    vlm_result: Mapping[str, Any] | None = None,
    downstream_evidence: Mapping[str, Any] | None = None,
    geometry_gate_evidence: Mapping[str, Any] | None = None,
    agent_collaboration: Mapping[str, Any] | None = None,
    elevation_evidence: Mapping[str, Any] | None = None,
    render_evidence: Mapping[str, Any] | None = None,
    certified_vlm_binding_required: bool = False,
) -> dict[str, Any]:
    """Build one truthful passport from evidence materialized for this MASS."""

    if (
        (compilation.metrics or {}).get("geometry_authority")
        == "certified_projected_visual_mesh"
    ):
        compilation = revalidate_compilation_mesh(compilation)
    program = compilation.program
    metadata = deepcopy(program.metadata or {})
    trace_by_id = {
        str(row.get("node_id") or ""): row
        for row in compilation.trace or ()
        if isinstance(row, dict)
    }
    measured_gate_issues = compilation_gate(compilation)
    gate_override = deepcopy(dict(geometry_gate_evidence or {}))
    explicit_gate_status = gate_override.get("hard_pass")
    gate_issues = measured_gate_issues
    gate_hard_pass = bool(
        not measured_gate_issues
        and explicit_gate_status is not False
    )
    program_issues = tuple(program.validate())
    preview = _resolved_render_evidence(
        preview_path,
        render_evidence,
        geometry_hash=str(compilation.geometry_hash or ""),
    )
    vlm = _resolved_vlm_evidence(
        vlm_result,
        compilation=compilation,
        render=preview,
        certified_binding_required=certified_vlm_binding_required,
    )
    collaboration = deepcopy(dict(agent_collaboration or {}))
    downstream = merge_agent_stage_evidence(
        normalize_downstream_evidence(metadata, downstream_evidence),
        collaboration,
    )
    book_projection = metadata.get("book_recursive_projection")
    book_projection = book_projection if isinstance(book_projection, dict) else {}
    program_projection = metadata.get("program_projection")
    program_projection = program_projection if isinstance(program_projection, dict) else {}
    ordered_nodes = _safe_topological_nodes(program)
    base_nodes = [node for node in ordered_nodes if node.kind == "primitive" or node.semantic_role == "base_seed"]
    book_nodes = [node for node in ordered_nodes if str((node.provenance or {}).get("source") or "") == "book_recursive_projection"]
    program_nodes = [
        node for node in ordered_nodes
        if str((node.provenance or {}).get("source") or "")
        in {"post_book_program_projection", "program_projection_connectivity_guard"}
    ]
    stages: list[dict[str, Any]] = [
        stage("base_model", "Base Model", "passed" if base_nodes else "failed", node_ids=[node.id for node in base_nodes], evidence={"operators": [node.operator for node in base_nodes], "seed_family": str(metadata.get("base_seed_family") or "")}),
        stage("book_language", "BOOK geometry language", "evaluated" if book_projection.get("active") else "not_evaluated", node_ids=[node.id for node in book_nodes], evidence={"scope_label": str(book_projection.get("scope_label") or ""), "scope_fraction": book_projection.get("scope_fraction"), "ordered_verbs": list(book_projection.get("ordered_verbs") or ()), "application_order": str(book_projection.get("application_order") or "")}),
        stage("recursive_geometry", "Recursive Geometry AST", "passed" if not program_issues else "failed", node_ids=[node.id for node in ordered_nodes], evidence={
            "root_id": program.root_id,
            "node_count": len(program.nodes),
            "issues": [issue.to_dict() for issue in program_issues],
            "form_bank_lane": str(metadata.get("form_bank_lane") or ""),
            "form_bank_variation_page": int(metadata.get("form_bank_variation_page") or 0),
            "program_conditioned": bool(metadata.get("program_conditioned")),
        }),
        stage("program", "Use / program projection", "passed" if metadata.get("program_projection_applied") else "not_evaluated", node_ids=[node.id for node in program_nodes], evidence=program_projection),
    ]
    stages.extend(stage_from_downstream(key, downstream[key]) for key in ("site", "capacity", "law", "parking", "program_fit"))
    stages.extend((
        stage("compiler", "Geometry Compiler", "passed" if compilation.status == "compiled" else "failed", node_ids=list(trace_by_id), evidence={
            "status": compilation.status,
            "trace_count": len(compilation.trace or ()),
            "issues": [issue.to_dict() for issue in compilation.issues or ()],
            "capacity_replay_numeric_transport": deepcopy(
                (compilation.metrics or {}).get(
                    "capacity_replay_numeric_transport"
                ) or {}
            ),
        }),
        stage("geometry_gate", "Geometry GATE", "passed" if gate_hard_pass else "failed", evidence={
            **gate_override,
            "hard_pass": gate_hard_pass,
            "issues": [issue.to_dict() for issue in gate_issues],
            "metrics": deepcopy(compilation.metrics or {}),
        }),
        stage("render", "Four-view PNG", preview["status"], evidence=preview),
        stage("vlm", "VLM critic", vlm["status"], evidence=vlm),
        stage_from_downstream("selector", downstream["selector"]),
    ))
    collaboration_status = str(collaboration.get("final_status") or "")
    collaboration_identity = (
        collaboration.get("identity")
        if isinstance(collaboration.get("identity"), Mapping)
        else {}
    )
    capacity_plan_hash = resolve_floor_capacity_plan_identity(
        program=program,
        capacity=downstream["capacity"],
        additional_hashes=(
            collaboration_identity.get("floor_capacity_plan_hash"),
        ),
        unresolved="FLOOR_CAPACITY_PLAN_HASH_UNRESOLVED",
    )
    stages.append(stage(
        "agent_collaboration",
        "Specialist agent collaboration",
        "passed" if collaboration_status == "accepted" else collaboration_status or "not_evaluated",
        evidence=collaboration,
    ))
    activation_graph = build_activation_graph(
        program=program,
        ordered_nodes=ordered_nodes,
        trace_by_id=trace_by_id,
        stages=stages,
        preview=preview,
        vlm=vlm,
        gate_issues=gate_issues,
        agent_collaboration=collaboration,
        geometry_hash=str(compilation.geometry_hash or ""),
        elevation_evidence=deepcopy(dict(elevation_evidence or {})),
    )
    state = passport_state(stages)
    visual_hash = (
        str(compilation.geometry_hash or "")
        if (
            compilation.status == "compiled"
            and not measured_gate_issues
            and (
                compilation.metrics or {}
            ).get("geometry_authority")
            == "certified_projected_visual_mesh"
        )
        else ""
    )
    return {
        "schema_version": MASS_EXECUTION_PASSPORT_SCHEMA,
        "mass_id": f"mass:{compilation.geometry_hash or _safe_program_hash(program)}",
        "program_name": program.name,
        "program_hash": _safe_program_hash(program),
        "structural_hash": _safe_structural_hash(program),
        "geometry_hash": str(compilation.geometry_hash or ""),
        "capacity_replay_numeric_transport": deepcopy(
            (compilation.metrics or {}).get(
                "capacity_replay_numeric_transport"
            ) or {}
        ),
        "visual_hash": visual_hash,
        "floor_capacity_plan_hash": capacity_plan_hash,
        **state,
        "truth_policy": {
            "unevaluated_is_never_pass": True,
            "execution_complete_is_not_acceptance": True,
            "internal_neuron_claim": False,
            "causal_program_trace": True,
            "visual_activation_uses_materialized_evidence_only": True,
        },
        "stages": stages,
        "activation_graph": activation_graph,
        "agent_collaboration": collaboration,
        "elevation_evidence": deepcopy(dict(elevation_evidence or {})),
    }


def _resolved_render_evidence(
    preview_path: str | Path | None,
    supplied: Mapping[str, Any] | None,
    *,
    geometry_hash: str,
) -> dict[str, Any]:
    if not isinstance(supplied, Mapping):
        return preview_evidence(preview_path)
    result = deepcopy(dict(supplied))
    path_value = str(result.get("path") or result.get("board_png") or "")
    path = Path(path_value) if path_value else None
    rendered_hash = str(
        result.get("projected_visual_geometry_hash")
        or result.get("geometry_hash")
        or ""
    )
    if not rendered_hash or not geometry_hash:
        raise ValueError("render evidence geometry identity is required")
    if rendered_hash != geometry_hash:
        raise ValueError(
            "render evidence geometry identity mismatch: "
            f"expected={geometry_hash or 'missing'} actual={rendered_hash}"
        )
    if path is None or not path.is_file():
        result.update({
            "status": "not_evaluated",
            "reason": "archive_render_file_missing",
        })
        return result
    try:
        with Image.open(path) as image:
            if image.format != "PNG":
                raise ValueError("render evidence PNG is invalid")
            image.verify()
        with Image.open(path) as image:
            width, height = image.size
    except (OSError, SyntaxError, UnidentifiedImageError) as exc:
        raise ValueError("render evidence PNG is invalid") from exc
    crop = result.get("crop_box")
    if (
        not isinstance(crop, (list, tuple))
        or len(crop) != 4
        or any(not isinstance(value, int) for value in crop)
    ):
        raise ValueError("render evidence crop is invalid")
    left, top, right, bottom = crop
    if not (
        0 <= left < right <= width
        and 0 <= top < bottom <= height
    ):
        raise ValueError("render evidence crop is invalid")
    content = path.read_bytes()
    hard_pass = bool(
        result.get("render_hard_pass")
        if "render_hard_pass" in result
        else result.get("hard_pass")
    )
    result.update({
        "status": "passed" if hard_pass else "failed",
        "path": str(path.resolve()),
        "sha256": hashlib.sha256(content).hexdigest(),
        "byte_count": len(content),
        "views": list(result.get("views") or ("portfolio_card",)),
    })
    return result


def _resolved_vlm_evidence(
    supplied: Mapping[str, Any] | None,
    *,
    compilation: Any,
    render: Mapping[str, Any],
    certified_binding_required: bool,
) -> dict[str, Any]:
    if not certified_binding_required:
        return vlm_evidence(supplied)
    value = deepcopy(dict(supplied or {}))
    binding = value.get("evidence_binding")
    binding = deepcopy(binding) if isinstance(binding, Mapping) else {}
    image_inputs = value.get("vlm_image_inputs")
    image_inputs = image_inputs if isinstance(image_inputs, Mapping) else {}
    candidate_input = image_inputs.get("candidate")
    candidate_input = (
        candidate_input if isinstance(candidate_input, Mapping) else {}
    )
    binding_schema = str(binding.get("schema_version") or "")
    binding_program_hash = str(binding.get("program_hash") or "")
    binding_geometry_hash = str(binding.get("geometry_hash") or "")
    binding_authority = str(binding.get("geometry_authority") or "")
    binding_candidate_sha256 = str(binding.get("candidate_sha256") or "")

    required_binding = (
        binding_schema == "arr.maas.vlm_evidence_binding.v1"
        and binding_program_hash
        and binding_geometry_hash
        and binding_authority == "certified_projected_visual_mesh"
        and binding_candidate_sha256
    )
    candidate_sha256 = str(candidate_input.get("sha256") or "")
    render_sha256 = str(render.get("sha256") or "")
    if (
        not required_binding
        or candidate_input.get("used_by_vlm") is not True
        or not candidate_sha256
        or not render_sha256
    ):
        return _unbound_vlm_evidence(
            value,
            binding=binding,
            reason="certified_vlm_evidence_binding_missing",
        )
    if (
        binding_program_hash != _safe_program_hash(compilation.program)
        or binding_geometry_hash != str(compilation.geometry_hash or "")
    ):
        return _unbound_vlm_evidence(
            value,
            binding=binding,
            reason="certified_vlm_geometry_binding_mismatch",
        )
    if (
        binding_candidate_sha256 != candidate_sha256
        or candidate_sha256 != render_sha256
    ):
        return _unbound_vlm_evidence(
            value,
            binding=binding,
            reason="certified_vlm_input_image_digest_mismatch",
        )
    return vlm_evidence(value)


def _unbound_vlm_evidence(
    source_audit: Mapping[str, Any],
    *,
    binding: Mapping[str, Any],
    reason: str,
) -> dict[str, Any]:
    evidence = vlm_evidence(source_audit)
    evidence.update({
        "status": "not_evaluated",
        "reason": reason,
        "hard_pass": False,
        "binding_status": "unbound",
        "evidence_binding": deepcopy(dict(binding)),
        "source_audit": deepcopy(dict(source_audit)),
    })
    return evidence


def enrich_mass_execution_passport(
    passport: Mapping[str, Any],
    *,
    downstream_evidence: Mapping[str, Any] | None = None,
    vlm_result: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach later site/capacity/law/parking/VLM facts without recompiling."""

    result = deepcopy(dict(passport))
    stages = result.get("stages")
    graph = result.get("activation_graph")
    if not isinstance(stages, list) or not isinstance(graph, dict):
        raise ValueError("invalid MASS execution passport")
    supplied = dict(downstream_evidence or {})
    updates = normalize_downstream_evidence({}, supplied)
    stage_map = {str(row.get("id") or ""): row for row in stages if isinstance(row, dict)}
    for stage_id in DOWNSTREAM_STAGE_KEYS:
        if stage_id in stage_map and any(key in supplied for key in DOWNSTREAM_ALIASES[stage_id]):
            stage_map[stage_id].update(stage_from_downstream(stage_id, updates[stage_id]))
    if vlm_result is not None and "vlm" in stage_map:
        vlm = vlm_evidence(vlm_result)
        stage_map["vlm"].update(stage("vlm", "VLM critic", vlm["status"], evidence=vlm))

    graph_nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
    graph_edges = graph.get("edges") if isinstance(graph.get("edges"), list) else []
    node_map = {str(node.get("id") or ""): node for node in graph_nodes if isinstance(node, dict)}
    for stage_id in (*DOWNSTREAM_STAGE_KEYS, "vlm"):
        row = stage_map.get(stage_id)
        node = node_map.get(f"flow:{stage_id}")
        if not row or not node:
            continue
        node["status"] = row["status"]
        node["activation"] = status_activation(row["status"])
        node["evidence"] = deepcopy(row.get("evidence") or {})
        for graph_edge in graph_edges:
            if isinstance(graph_edge, dict) and graph_edge.get("target") == node["id"]:
                graph_edge["activation"] = node["activation"]
    if vlm_result is not None:
        append_vlm_nodes(graph_nodes, graph_edges, vlm_evidence(vlm_result))
    result.update(passport_state(stages))
    return result


def _safe_topological_nodes(program: Any) -> tuple[Any, ...]:
    try:
        return tuple(program.topological_nodes())
    except ValueError:
        return tuple(program.nodes or ())


def _safe_program_hash(program: Any) -> str:
    try:
        return str(program.program_hash())
    except ValueError:
        return ""


def _safe_structural_hash(program: Any) -> str:
    try:
        return str(program.canonical_structure_hash())
    except ValueError:
        return ""


__all__ = [
    "MASS_EXECUTION_PASSPORT_SCHEMA",
    "build_mass_execution_passport",
    "enrich_mass_execution_passport",
    "passport_path_for_preview",
    "write_mass_execution_passport",
]
