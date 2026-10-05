"""
Interactive mass-design patch planning.

M1 scope: translate a user's natural-language design request into a
structured, validator-safe patch plan. This module does not mutate optimizer
inputs yet; it returns dry-run candidates that the UI can show and later feed
into a real repair/evaluation pass.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class PatchCandidate:
    """One possible mass-edit plan."""

    id: str
    title: str
    intent: str
    patch: dict[str, Any]
    constraints: list[str]
    expected_effects: list[str]
    risks: list[str] = field(default_factory=list)


@dataclass
class InteractivePatchPlan:
    """Response returned to the frontend."""

    mode: str
    user_text: str
    selected_design_id: int | None
    interpreted_intents: list[str]
    candidates: list[PatchCandidate]
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["candidates"] = [asdict(c) for c in self.candidates]
        return data


def _norm(text: str) -> str:
    return (text or "").strip().lower()


def _has_any(text: str, words: tuple[str, ...]) -> bool:
    return any(w in text for w in words)


def _direction_from_text(text: str) -> str:
    """Infer explicit core direction without treating words like '동선' as east."""
    if _has_any(text, ("동측", "동쪽", "동편", "east")):
        return "east"
    if _has_any(text, ("서측", "서쪽", "서편", "west")):
        return "west"
    if _has_any(text, ("남측", "남쪽", "남편", "south")):
        return "south"
    if _has_any(text, ("북측", "북쪽", "북편", "north")):
        return "north"
    return "edge"


def _selected_metrics(design: dict[str, Any] | None, mass_geojson: dict[str, Any] | None) -> dict[str, Any]:
    props = (mass_geojson or {}).get("properties") or {}
    return {
        "height": props.get("height"),
        "num_floors": props.get("num_floors"),
        "floor_height": props.get("floor_height"),
        "far": props.get("far"),
        "bcr": props.get("bcr"),
        "floor_area": props.get("floor_area"),
        "mass_shape": props.get("mass_shape") or (design or {}).get("algorithm"),
        "has_stepback": bool(props.get("step_floor") or props.get("upper_geometry")),
    }


def build_interactive_patch_plan(
    user_text: str,
    selected_design: dict[str, Any] | None = None,
    mass_geojson: dict[str, Any] | None = None,
    constraints: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Create dry-run patch candidates from a user design request.

    This is deliberately deterministic and dependency-free for M1. LLM parsing
    can be added later behind the same response schema.
    """
    text = _norm(user_text)
    selected_design_id = None
    if selected_design:
        selected_design_id = selected_design.get("id")
        if selected_design_id is None:
            selected_design_id = selected_design.get("design_id")

    metrics = _selected_metrics(selected_design, mass_geojson)
    known_constraints = {c.get("name") for c in (constraints or []) if isinstance(c, dict)}

    interpreted: list[str] = []
    candidates: list[PatchCandidate] = []
    notes = [
        "M1 dry-run: 후보는 설계 파라미터 변경 계획이며 아직 optimizer inputs를 수정하지 않습니다.",
        "최종 채택 전 FAR/BCR/높이/이격/정북일조 validator gate를 반드시 통과해야 합니다.",
    ]

    if not text:
        return InteractivePatchPlan(
            mode="dry_run",
            user_text=user_text,
            selected_design_id=selected_design_id,
            interpreted_intents=[],
            candidates=[],
            notes=["수정 요청 문장이 비어 있습니다."],
        ).to_dict()

    north_related = _has_any(text, ("북", "정북", "일조", "사선"))
    upper_related = _has_any(text, ("후퇴", "상층", "상부", "낮춰", "낮추"))
    if north_related or upper_related:
        interpreted.append("north_sunlight_stepback")
        target_side = "north" if north_related else "upper"
        candidates.append(PatchCandidate(
            id="smooth-north-stepback",
            title="북측 상부 후퇴를 단계적으로 완화" if target_side == "north" else "상부 후퇴를 단계적으로 완화",
            intent="smooth_stepback",
            patch={
                "target_side": target_side,
                "num_steps": 3 if metrics["has_stepback"] else 2,
                "max_far_loss_pct": 5,
                "prefer_parameter_patch": True,
            },
            constraints=["north_sunlight", "far", "height"] if target_side == "north" else ["far", "height", "setback"],
            expected_effects=[
                "정북일조 위반 위험을 유지하면서 상부 매스 전이를 부드럽게 만듭니다."
                if target_side == "north"
                else "상부 매스 전이를 부드럽게 만들고 면적 손실을 제한합니다.",
                "상층부 면적 손실을 5% 이내로 제한하는 후보부터 검토합니다.",
            ],
            risks=["용적률 손실", "상층부 평면 효율 저하"],
        ))

    if _has_any(text, ("도로", "저층", "포디움", "기단", "1층", "2층", "3층", "가로", "전면")):
        interpreted.append("road_side_podium")
        candidates.append(PatchCandidate(
            id="strengthen-road-podium",
            title="도로측 저층부 포디움 강화",
            intent="strengthen_podium",
            patch={
                "target_side": "road",
                "podium_floors": 3,
                "podium_scale_delta": 0.08,
                "compensate_upper_mass": True,
            },
            constraints=["road_setback", "bcr", "far"],
            expected_effects=[
                "도로측 저층부 존재감을 키우고 가로 대응을 강화합니다.",
                "BCR/FAR 증가분은 상층부 축소로 보정합니다.",
            ],
            risks=["도로 후퇴 위반", "건폐율 증가"],
        ))

    if _has_any(text, ("코어", "계단", "엘리베이터", "동선", "피난", "중앙", "동측", "서측", "남측")):
        interpreted.append("core_relocation")
        target = _direction_from_text(text)
        candidates.append(PatchCandidate(
            id="move-core-to-edge",
            title="코어를 외곽으로 이동 검토",
            intent="move_core",
            patch={
                "target": target,
                "preserve_escape_distance_m": 30,
                "avoid_daylight_loss": True,
            },
            constraints=["inside_footprint", "egress_distance", "floor_efficiency"],
            expected_effects=[
                "중앙부 평면 활용도를 높이고 서비스 코어를 한쪽으로 정리합니다.",
                "피난거리 30m 이내와 footprint 내부 포함 여부를 재검증합니다.",
            ],
            risks=["피난거리 초과", "코어가 좁은 매스에 들어가지 않을 가능성"],
        ))

    if _has_any(text, ("뚱뚱", "박스", "답답", "슬림", "날씬", "비례", "예쁘", "자연스럽")):
        interpreted.append("proportion_refinement")
        candidates.append(PatchCandidate(
            id="refine-mass-proportion",
            title="매스 비례 개선",
            intent="refine_proportion",
            patch={
                "height_width_rebalance": True,
                "max_floor_area_loss_pct": 3,
                "try_typology_shift": ["tower_podium", "lshape", "subtractive"],
            },
            constraints=["far", "bcr", "setback", "height"],
            expected_effects=[
                "너무 단순한 박스 인상을 줄이고 수직/수평 비례를 조정합니다.",
                "면적 손실을 3% 이내로 제한한 후보를 우선합니다.",
            ],
            risks=["형태 변경에 따른 면적 손실", "기존 최적화 목적함수 점수 저하"],
        ))

    if _has_any(text, ("용적", "far", "면적", "연면적", "더 크게", "키워", "올려", "최대")):
        interpreted.append("far_utilization")
        candidates.append(PatchCandidate(
            id="increase-far-with-gate",
            title="용적률 활용도 상승 후보",
            intent="increase_far",
            patch={
                "target_far_delta_pct": 3,
                "respect_existing_envelope": True,
                "prefer_vertical_growth": True,
            },
            constraints=["far", "height", "north_sunlight", "daylight_diagonal"],
            expected_effects=[
                "법규 envelope가 허용하는 범위에서 면적을 회복합니다.",
                "상층부 수직 증축이 불가능하면 저층부/중층부 보정을 검토합니다.",
            ],
            risks=["정북일조 또는 높이 제한 위반", "일조 점수 하락"],
        ))

    if not candidates:
        interpreted.append("general_design_review")
        candidates.append(PatchCandidate(
            id="general-review",
            title="일반 설계 리뷰 후 후보 생성",
            intent="general_review",
            patch={
                "review_targets": ["mass_proportion", "far", "bcr", "core", "setback"],
                "generate_alternatives": 2,
            },
            constraints=["far", "bcr", "height", "setback"],
            expected_effects=[
                "요청이 구체적이지 않아 매스 비례, 면적, 코어, 이격을 종합 검토합니다.",
            ],
            risks=["수정 방향이 사용자 의도와 다를 수 있음"],
        ))

    if "height_limit" in known_constraints or "height" in known_constraints:
        notes.append("현재 job constraints에 높이 제한이 포함되어 있어 수직 증축 후보는 보수적으로 처리합니다.")

    return InteractivePatchPlan(
        mode="dry_run",
        user_text=user_text,
        selected_design_id=selected_design_id,
        interpreted_intents=interpreted,
        candidates=candidates,
        notes=notes,
    ).to_dict()


__all__ = ["build_interactive_patch_plan"]
