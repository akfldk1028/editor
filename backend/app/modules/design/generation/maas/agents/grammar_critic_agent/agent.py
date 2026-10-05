"""Grammar critic agent for MAAS candidate diversity and evidence checks."""

from __future__ import annotations

from typing import Any

from backend.app.modules.design.generation.maas.agents.shared.types import AgentCard, AgentContext, AgentResult


GRAMMAR_REVIEW_SCHEMA_VERSION = "arr.maas.grammar_review.v1"


def _props(feature: dict[str, Any]) -> dict[str, Any]:
    props = feature.get("properties")
    return props if isinstance(props, dict) else {}


def _sequence_verbs(props: dict[str, Any]) -> list[str]:
    sequence = props.get("maas_verb_sequence")
    if not isinstance(sequence, list):
        model = props.get("maas_model")
        sequence = model.get("verb_sequence") if isinstance(model, dict) else []
    return [
        str(item.get("verb"))
        for item in sequence
        if isinstance(item, dict) and item.get("verb") and item.get("verb") != "base"
    ]


def build_grammar_review(
    feature: dict[str, Any],
    *,
    rejected: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    props = _props(feature)
    verbs = _sequence_verbs(props)
    signature = props.get("source_signature")
    if not isinstance(signature, dict):
        model = props.get("maas_model")
        signature = model.get("source_signature") if isinstance(model, dict) else {}
    family = signature.get("family") if isinstance(signature, dict) else None
    volume_count = signature.get("volume_count") if isinstance(signature, dict) else None
    surface_count = signature.get("surface_count") if isinstance(signature, dict) else None
    connector_verbs = {"diagonal_connect", "terrace_link", "sloped_roof_mass", "grade", "taper", "shift"}
    has_section_language = bool(connector_verbs & set(verbs)) or (isinstance(volume_count, int) and volume_count > 1)
    has_source_surface_contract = isinstance(surface_count, int) and surface_count > 0
    has_parking = bool((props.get("parking_precheck") or {}).get("layout_candidate"))
    visual_evidence = props.get("visual_diversity_evidence")
    if not isinstance(visual_evidence, dict):
        model = props.get("maas_model")
        visual_evidence = model.get("visual_diversity_evidence") if isinstance(model, dict) else {}
    geometry_resolution = props.get("geometry_resolution")
    if not isinstance(geometry_resolution, dict):
        model = props.get("maas_model")
        geometry_resolution = model.get("geometry_resolution") if isinstance(model, dict) else {}
    legal_metrics = {
        "far": props.get("far"),
        "bcr": props.get("bcr"),
        "height": props.get("height"),
    }
    ambition = props.get("architectural_ambition_evidence")
    if not isinstance(ambition, dict) and isinstance(signature, dict):
        ambition = signature.get("architectural_ambition_evidence")
    if not isinstance(ambition, dict):
        ambition = {}
    orderliness = props.get("orderliness_evidence")
    if not isinstance(orderliness, dict) and isinstance(visual_evidence, dict):
        nested_orderliness = visual_evidence.get("orderliness_evidence")
        orderliness = nested_orderliness if isinstance(nested_orderliness, dict) else {}
    elif not isinstance(orderliness, dict):
        orderliness = {}
    issues: list[str] = []
    if not verbs:
        issues.append("missing_massdsl_sequence")
    if not has_section_language:
        issues.append("weak_section_or_connector_language")
    if not has_source_surface_contract:
        issues.append("missing_source_surface_contract")
    if not has_parking:
        issues.append("missing_parking_layout_evidence")
    if not visual_evidence:
        issues.append("missing_visual_diversity_evidence")
    elif visual_evidence.get("stepback_like") and visual_evidence.get("visual_family") not in {"stepback_tower", "legal_layered"}:
        issues.append("non_step_family_rendered_as_stepback")
    if not geometry_resolution:
        issues.append("missing_geometry_resolution")
    order_score = float(orderliness.get("orderliness_score") or 0.0)
    if order_score < 0.74:
        issues.append("low_architectural_orderliness")
    if int(orderliness.get("small_fragment_count") or 0) > 1:
        issues.append("too_many_small_fragments")
    if int(surface_count or 0) > 72:
        issues.append("over_complex_source_surface_contract")
    if orderliness.get("unclear_language_mix"):
        issues.append("unclear_language_mix")
    if not (ambition.get("has_formal_principle") or ambition.get("formal_principle")):
        issues.append("missing_formal_principle")
    if not (ambition.get("has_dominant_gesture") or ambition.get("dominant_gesture")):
        issues.append("missing_dominant_gesture")
    if not ambition.get("architecture_grade_pass"):
        issues.append("architecture_grade_not_implemented")
    status = "pass" if not issues else "check"

    return {
        "schema_version": GRAMMAR_REVIEW_SCHEMA_VERSION,
        "status": status,
        "family": family,
        "verbs": verbs,
        "volume_count": volume_count,
        "surface_count": surface_count,
        "has_section_language": has_section_language,
        "has_source_surface_contract": has_source_surface_contract,
        "has_parking_evidence": has_parking,
        "visual_diversity_evidence": visual_evidence,
        "orderliness_evidence": orderliness,
        "architectural_ambition_evidence": ambition,
        "geometry_resolution": geometry_resolution,
        "legal_metrics": legal_metrics,
        "rejected_candidate_count": len(rejected or []),
        "issues": issues,
    }


class GrammarCriticAgent:
    agent_id = "grammar_critic_agent"
    display_name = "Grammar Critic Agent"
    role = "Critique massing language diversity, section connectors, and evidence completeness."

    def run(self, context: AgentContext) -> AgentResult:
        review = build_grammar_review(context.feature, rejected=context.rejected)
        return AgentResult(
            agent=self.agent_id,
            status=review["status"],
            summary=(
                f"grammar family={review.get('family')}; "
                f"verbs={len(review.get('verbs') or [])}; issues={len(review.get('issues') or [])}"
            ),
            metrics={"grammar_review": review},
            role=self.role,
            next_agent="review_agent",
        )

    def build_card(self) -> dict[str, Any]:
        return AgentCard(
            name=self.agent_id,
            display_name=self.display_name,
            description=self.role,
            skills=["grammar_diversity_review", "section_language_review", "parking_evidence_gate"],
            endpoint="/design/maas/agents/grammar_critic_agent",
            output_schema=GRAMMAR_REVIEW_SCHEMA_VERSION,
        ).to_dict()


__all__ = ["GRAMMAR_REVIEW_SCHEMA_VERSION", "GrammarCriticAgent", "build_grammar_review"]
