"""LLM architectural-language agent for MAAS.

The live OpenAI population call is owned by ``design.maas.llm_proposals``.
This agent owns the review contract for that LLM output inside the MAAS
multi-agent flow, so LLM-authored language is not an orphan module outside the
agent graph.
"""

from __future__ import annotations

from typing import Any

from backend.app.modules.design.generation.maas.agents.shared.types import AgentCard, AgentContext, AgentResult


LLM_ARCHITECT_REVIEW_SCHEMA_VERSION = "arr.maas.llm_architect_review.v1"


def _props(feature: dict[str, Any]) -> dict[str, Any]:
    props = feature.get("properties")
    return props if isinstance(props, dict) else {}


def _model(props: dict[str, Any]) -> dict[str, Any]:
    model = props.get("maas_model")
    return model if isinstance(model, dict) else {}


def _source_signature(props: dict[str, Any]) -> dict[str, Any]:
    signature = props.get("source_signature")
    if isinstance(signature, dict):
        return signature
    model = _model(props)
    signature = model.get("source_signature")
    return signature if isinstance(signature, dict) else {}


def _llm_proposal(props: dict[str, Any]) -> dict[str, Any]:
    proposal = props.get("llm_massdsl_proposal")
    if isinstance(proposal, dict):
        return proposal
    model = _model(props)
    proposal = model.get("llm_massdsl_proposal")
    return proposal if isinstance(proposal, dict) else {}


def _massdsl_proposal(props: dict[str, Any]) -> dict[str, Any]:
    proposal = props.get("massdsl_proposal")
    if isinstance(proposal, dict):
        return proposal
    model = _model(props)
    proposal = model.get("massdsl_proposal")
    return proposal if isinstance(proposal, dict) else {}


def build_llm_architect_review(feature: dict[str, Any]) -> dict[str, Any]:
    props = _props(feature)
    signature = _source_signature(props)
    llm_proposal = _llm_proposal(props)
    massdsl = _massdsl_proposal(props)
    design_parameters = massdsl.get("design_parameters") if isinstance(massdsl.get("design_parameters"), dict) else {}
    rule_evidence = signature.get("rule_evidence")
    if not isinstance(rule_evidence, dict):
        rule_evidence = design_parameters.get("rule_evidence") if isinstance(design_parameters.get("rule_evidence"), dict) else {}
    primary_language = str(signature.get("primary_language") or "")
    secondary_language = str(signature.get("secondary_language") or "")
    composition_rule = str(signature.get("composition_rule") or "")
    parameter_source = str(design_parameters.get("parameter_source") or design_parameters.get("source") or "")
    issues: list[str] = []
    if not llm_proposal and parameter_source == "llm_arch_language_proposal":
        issues.append("missing_raw_llm_massdsl_proposal")
    if parameter_source != "llm_arch_language_proposal":
        issues.append("not_llm_authored_parameter_source")
    if not primary_language:
        issues.append("missing_primary_language")
    if not secondary_language or secondary_language == "legal_envelope_fit":
        issues.append("missing_secondary_architectural_language")
    if not composition_rule:
        issues.append("missing_composition_rule")
    if not rule_evidence:
        issues.append("missing_rule_evidence")
    status = "pass" if not issues else "check"
    return {
        "schema_version": LLM_ARCHITECT_REVIEW_SCHEMA_VERSION,
        "status": status,
        "mass_shape": props.get("mass_shape"),
        "parameter_source": parameter_source,
        "primary_language": primary_language,
        "secondary_language": secondary_language,
        "composition_rule": composition_rule,
        "rule_name": rule_evidence.get("rule_name") if isinstance(rule_evidence, dict) else None,
        "llm_proposal_id": llm_proposal.get("proposal_id") if isinstance(llm_proposal, dict) else None,
        "topology_intent": llm_proposal.get("topology_intent") if isinstance(llm_proposal, dict) else None,
        "issues": issues,
    }


class LLMArchitectAgent:
    agent_id = "llm_architect_agent"
    display_name = "LLM Architect Agent"
    role = "Own LLM-authored architectural language before MassDSL validation."

    def propose_population(self, *, site_context: dict[str, Any], **kwargs: Any):
        """Generate the live architectural-language population owned by this agent.

        Keeping the OpenAI adapter in ``llm_proposals`` preserves provider
        modularity, while this method makes the runtime ownership match the
        documented multi-agent flow instead of using the agent only as a
        post-hoc reviewer.
        """
        from backend.app.modules.design.generation.maas.llm_proposals import LlmProposalBatch, generate_llm_massdsl_batch

        batch = generate_llm_massdsl_batch(site_context=site_context, **kwargs)
        artifact = dict(batch.artifact)
        artifact.update({
            "owning_agent": self.agent_id,
            "agent_operation": "architectural_language_population_proposal",
            "site_geometry_status": str(
                (site_context.get("site_geometry_intelligence") or {}).get("status") or "missing"
            ),
        })
        return LlmProposalBatch(artifact=artifact, sequences=batch.sequences)

    def run(self, context: AgentContext) -> AgentResult:
        review = build_llm_architect_review(context.feature)
        return AgentResult(
            agent=self.agent_id,
            status=review["status"],
            summary=(
                f"LLM language {review['status']}; "
                f"{review.get('primary_language') or 'unknown'} + "
                f"{review.get('secondary_language') or 'none'}"
            ),
            metrics={"llm_architect_review": review},
            role=self.role,
            next_agent="massdsl_agent",
        )

    def build_card(self) -> dict[str, Any]:
        return AgentCard(
            name=self.agent_id,
            display_name=self.display_name,
            description=self.role,
            skills=[
                "llm_architectural_language_review",
                "primary_secondary_language_check",
                "llm_parameter_source_audit",
            ],
            endpoint="/design/maas/agents/llm_architect_agent",
            output_schema=LLM_ARCHITECT_REVIEW_SCHEMA_VERSION,
        ).to_dict()


__all__ = [
    "LLM_ARCHITECT_REVIEW_SCHEMA_VERSION",
    "LLMArchitectAgent",
    "build_llm_architect_review",
]
