"""Canonical MAAS law-to-design agent flow."""

from __future__ import annotations


REVIEW_AGENT_SEQUENCE = (
    "law_graph_agent",
    "master_plan_agent",
    "llm_architect_agent",
    "massdsl_agent",
    "maas_geometry_agent",
    "grammar_critic_agent",
    "preference_distiller_agent",
    "review_agent",
)

FLOW_AGENT_SEQUENCE = (
    "design_orchestrator",
    *REVIEW_AGENT_SEQUENCE,
)

FLOW_STEPS = [
    ("user", "design_orchestrator", "PNU/design 후보를 받으면 법규-주차-MassDSL-매스-문법검토 순서로 협업을 시작해."),
    ("design_orchestrator", "law_graph_agent", "Graph DB 법규 근거와 누락 evidence를 rule_id 중심으로 확인해."),
    ("law_graph_agent", "master_plan_agent", "법규 검토 결과를 받아 주차 산정 대수와 연접/차로 조건을 검토해."),
    ("master_plan_agent", "llm_architect_agent", "주차/법규 조건을 받아 LLM-authored 건축언어와 MassDSL 의도를 검토해."),
    ("llm_architect_agent", "massdsl_agent", "LLM 건축언어를 MassDSL sequence와 parameter-source contract로 넘겨."),
    ("massdsl_agent", "maas_geometry_agent", "MassDSL proposal을 source geometry와 MAAS repair 후보로 컴파일해."),
    ("maas_geometry_agent", "grammar_critic_agent", "컴파일된 매스의 도형언어, section connector, evidence 완결성을 검토해."),
    ("grammar_critic_agent", "preference_distiller_agent", "법규 통과 후보의 PNG/VLM/선호 증류 가능성을 검토하고 취향 점수를 hard-gate 뒤에 붙여."),
    ("preference_distiller_agent", "review_agent", "선호 점수를 법규/주차/MassDSL/매스 evidence와 분리해서 최종 검토로 넘겨."),
    ("review_agent", "design_orchestrator", "최종 판단과 다음 수정 지시를 사용자에게 전달할 형태로 정리해."),
]


def build_flow_edges() -> list[dict[str, str]]:
    return [
        {"source": source, "target": target, "label": message}
        for source, target, message in FLOW_STEPS
    ]


__all__ = ["FLOW_AGENT_SEQUENCE", "FLOW_STEPS", "REVIEW_AGENT_SEQUENCE", "build_flow_edges"]
