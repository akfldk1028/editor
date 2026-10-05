"""MassDSL proposal agent for deterministic MAAS grammar reviews."""

from __future__ import annotations

from typing import Any

from backend.app.modules.design.generation.maas.agents.shared.types import AgentCard, AgentContext, AgentResult


MASSDSL_SCHEMA_VERSION = "arr.maas.massdsl.proposal.v1"
PROPOSAL_SOURCE = "deterministic_agent_contract"
DETERMINISTIC_PARAMETER_SOURCE = "deterministic_sequence_library"
LLM_PARAMETER_SOURCE = "llm_arch_language_proposal"


def _feature_props(feature: dict[str, Any]) -> dict[str, Any]:
    props = feature.get("properties")
    return props if isinstance(props, dict) else {}


def _verb_sequence(props: dict[str, Any]) -> list[dict[str, Any]]:
    sequence = props.get("maas_verb_sequence")
    if isinstance(sequence, list):
        return [dict(item) for item in sequence if isinstance(item, dict)]
    model = props.get("maas_model")
    if isinstance(model, dict) and isinstance(model.get("verb_sequence"), list):
        return [dict(item) for item in model["verb_sequence"] if isinstance(item, dict)]
    return []


def build_massdsl_proposal(
    feature: dict[str, Any],
    *,
    operation_type: str,
    constraints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a compact, serializable MassDSL proposal from a selected candidate."""
    props = _feature_props(feature)
    model = props.get("maas_model") if isinstance(props.get("maas_model"), dict) else {}
    sequence = _verb_sequence(props)
    source_signature = props.get("source_signature")
    if not isinstance(source_signature, dict):
        source_signature = model.get("source_signature") if isinstance(model, dict) else None
    constraints = constraints or {}
    status = "valid" if sequence and (not sequence[0].get("verb") or sequence[0].get("verb") == "base") else "derived"
    if not sequence:
        status = "missing_sequence"

    source_status = props.get("source_geometry_status")
    if not source_status and isinstance(model, dict):
        source_status = model.get("source_geometry_status")
    source_surfaces = props.get("source_surfaces")
    if not isinstance(source_surfaces, list) and isinstance(model, dict):
        source_surfaces = model.get("source_surfaces")
    surface_count = len(source_surfaces) if isinstance(source_surfaces, list) else (
        source_signature.get("surface_count") if isinstance(source_signature, dict) else None
    )

    design_parameters = _design_parameters(props, sequence, source_signature)
    return {
        "schema_version": MASSDSL_SCHEMA_VERSION,
        "proposal_id": f"massdsl:{props.get('variant_id') or props.get('mass_shape') or 'candidate'}",
        "proposal_source": PROPOSAL_SOURCE,
        "intent": {
            "operation_type": operation_type,
            "mass_shape": props.get("mass_shape"),
            "grammar_label": model.get("grammar_label") if isinstance(model, dict) else None,
            "family": source_signature.get("family") if isinstance(source_signature, dict) else props.get("operator_family"),
        },
        "verb_sequence": sequence,
        "design_parameters": design_parameters,
        "fallback_rank": _fallback_rank(sequence, source_signature),
        "constraints": {
            "far_limit": constraints.get("far_limit"),
            "bcr_limit": constraints.get("bcr_limit"),
            "height_limit": constraints.get("height_limit"),
        },
        "source_refs": {
            "source_geometry_status": source_status,
            "source_signature": source_signature,
            "source_surface_count": surface_count,
        },
        "rationale": _proposal_rationale(props, sequence, source_signature),
        "validation_status": status,
    }


def _design_parameters(
    props: dict[str, Any],
    sequence: list[dict[str, Any]],
    source_signature: dict[str, Any] | None,
) -> dict[str, Any]:
    """Extract the proposal parameters that should drive geometry generation.

    The contract intentionally copies values from the MassDSL verb sequence
    instead of inventing materializer constants. The legal solver may clip or
    reject these values later, but geometry should start from this proposal.
    """
    llm_proposal = props.get("llm_massdsl_proposal")
    if isinstance(llm_proposal, dict):
        llm_params = llm_proposal.get("design_parameters")
        if isinstance(llm_params, dict):
            proposal = dict(llm_params)
            proposal.setdefault("source", LLM_PARAMETER_SOURCE)
            proposal["parameter_source"] = LLM_PARAMETER_SOURCE
            proposal["requires_llm_authoring"] = False
            proposal["legal_solver_role"] = "validate_clip_or_reject_only"
            _attach_rule_evidence(proposal, source_signature)
            return proposal

    research_basis = props.get("research_basis")
    if not isinstance(research_basis, dict):
        model = props.get("maas_model")
        if isinstance(model, dict):
            research_basis = model.get("research_basis")
    if isinstance(research_basis, dict) and research_basis.get("requires_llm_authoring") is False:
        source = str(research_basis.get("parameter_source") or LLM_PARAMETER_SOURCE)
        intended_role = (
            "supplied_by_openai_structured_massdsl_proposal_loop"
            if source == LLM_PARAMETER_SOURCE else
            "already supplied by clone/MAAS architectural language proposal artifact"
        )
        proposal: dict[str, Any] = {
            "family": source_signature.get("family") if isinstance(source_signature, dict) else None,
            "source": source,
            "parameter_source": source,
            "requires_llm_authoring": False,
            "intended_llm_role": intended_role,
            "legal_solver_role": "validate_clip_or_reject_only",
            "verbs": [str(item.get("verb")) for item in sequence if isinstance(item, dict) and item.get("verb")],
        }
        for item in sequence:
            if not isinstance(item, dict) or item.get("verb") == "base":
                continue
            verb = str(item.get("verb"))
            params = item.get("params") if isinstance(item.get("params"), dict) else {}
            proposal[verb] = dict(params)
        if isinstance(source_signature, dict):
            proposal["source_area_profile_m2"] = source_signature.get("area_profile_m2")
            proposal["source_upper_to_ground_ratio"] = source_signature.get("upper_to_ground_ratio")
            _attach_rule_evidence(proposal, source_signature)
        return proposal

    mass_shape = str(props.get("mass_shape") or "")
    family = source_signature.get("family") if isinstance(source_signature, dict) else None
    if mass_shape == "legal_layered_max" or family in {"legal_layered", "legal_buildable"}:
        proposal = {
            "family": family,
            "source": "legal_envelope_solver",
            "parameter_source": "legal_envelope_solver",
            "requires_llm_authoring": False,
            "intended_llm_role": "not_applicable_capacity_anchor",
            "legal_solver_role": "source_of_truth",
            "verbs": [str(item.get("verb")) for item in sequence if isinstance(item, dict) and item.get("verb")],
            "source_area_profile_m2": source_signature.get("area_profile_m2") if isinstance(source_signature, dict) else None,
        }
        _attach_rule_evidence(proposal, source_signature)
        return proposal

    params_by_verb = {
        str(item.get("verb") or ""): item.get("params") if isinstance(item.get("params"), dict) else {}
        for item in sequence
        if isinstance(item, dict)
    }
    family = source_signature.get("family") if isinstance(source_signature, dict) else None
    proposal: dict[str, Any] = {
        "family": family,
        "source": "verb_sequence_params",
        "parameter_source": DETERMINISTIC_PARAMETER_SOURCE,
        "requires_llm_authoring": True,
        "authoring_gap": "typology mix and numeric design ratios are deterministic library inputs, not live LLM architectural judgment",
        "intended_llm_role": "choose MassDSL verbs and ratios from architectural language before deterministic legal validation",
        "legal_solver_role": "validate_clip_or_reject_only",
        "verbs": [str(item.get("verb")) for item in sequence if isinstance(item, dict) and item.get("verb")],
    }
    for verb, params in params_by_verb.items():
        if verb == "base":
            continue
        proposal[verb] = dict(params)
    if isinstance(source_signature, dict):
        proposal["source_area_profile_m2"] = source_signature.get("area_profile_m2")
        proposal["source_upper_to_ground_ratio"] = source_signature.get("upper_to_ground_ratio")
        _attach_rule_evidence(proposal, source_signature)
    return proposal


def _attach_rule_evidence(proposal: dict[str, Any], source_signature: dict[str, Any] | None) -> None:
    if not isinstance(source_signature, dict):
        return
    rule_evidence = source_signature.get("rule_evidence")
    if isinstance(rule_evidence, dict):
        proposal["rule_evidence"] = rule_evidence
        proposal["rule_prior_param_ratio"] = source_signature.get("rule_prior_param_ratio")
        proposal["invalid_rule_param_count"] = source_signature.get("invalid_rule_param_count")


def _fallback_rank(
    sequence: list[dict[str, Any]],
    source_signature: dict[str, Any] | None,
) -> list[str]:
    rank = ["compile_source_geometry", "clip_to_legal_envelope", "reject_with_reason"]
    family = source_signature.get("family") if isinstance(source_signature, dict) else None
    verbs = {
        str(item.get("verb"))
        for item in sequence
        if isinstance(item, dict) and item.get("verb")
    }
    if family in {"stepback_tower", "legal_layered"} or "step_envelope" in verbs:
        rank.insert(1, "legal_floor_plate_stack")
    else:
        rank.append("fallback_floor_plate_stack")
    return rank


def _proposal_rationale(
    props: dict[str, Any],
    sequence: list[dict[str, Any]],
    source_signature: dict[str, Any] | None,
) -> str:
    verbs = [str(item.get("verb")) for item in sequence if isinstance(item, dict) and item.get("verb")]
    family = source_signature.get("family") if isinstance(source_signature, dict) else None
    if verbs:
        return f"MassDSL verbs {', '.join(verbs)} explain {props.get('mass_shape')} as family={family or 'unknown'}."
    return f"No explicit MassDSL verb sequence is attached to {props.get('mass_shape')}; candidate remains geometry-derived."


class MassDSLAgent:
    agent_id = "massdsl_agent"
    display_name = "MassDSL Agent"
    role = "Propose and validate a MassDSL grammar recipe before geometry compilation."

    def run(self, context: AgentContext) -> AgentResult:
        proposal = build_massdsl_proposal(
            context.feature,
            operation_type=context.operation_type,
            constraints=context.constraints,
        )
        status = "pass" if proposal["validation_status"] == "valid" else "needs_evidence"
        sequence = proposal["verb_sequence"]
        return AgentResult(
            agent=self.agent_id,
            status=status,
            summary=f"MassDSL proposal {proposal['validation_status']}; verbs={len(sequence)}",
            metrics={
                "proposal": proposal,
                "verb_count": len(sequence),
                "mass_shape": proposal["intent"].get("mass_shape"),
            },
            role=self.role,
            next_agent="maas_geometry_agent",
        )

    def build_card(self) -> dict[str, Any]:
        return AgentCard(
            name=self.agent_id,
            display_name=self.display_name,
            description=self.role,
            skills=["massdsl_proposal", "verb_sequence_validation", "source_geometry_contract"],
            endpoint="/design/maas/agents/massdsl_agent",
            output_schema=MASSDSL_SCHEMA_VERSION,
        ).to_dict()


__all__ = ["MASSDSL_SCHEMA_VERSION", "MassDSLAgent", "build_massdsl_proposal"]
