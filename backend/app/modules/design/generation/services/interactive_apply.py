"""
Apply interactive patch candidates to existing mass inputs.

M2 scope: create previewable, validator-gated alternatives without rerunning
the full optimizer. The current mass genome supports one global two-tier
stepback, so free-form requests are approximated through conservative global
gene changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.app.modules.design.generation.engine.objects import Design
from backend.app.modules.design.generation.services.constraint_bridge import build_default_job_spec
from backend.app.modules.design.generation.services.mass_evaluator import ALGO_LAYOUT, evaluate_designs
from backend.app.modules.design.generation.services.mass_renderer import design_to_geojson
from backend.app.modules.design.generation.services.site_geometry import geojson_to_polygon


@dataclass
class CandidateSpec:
    id: str
    title: str
    intent: str
    patch: dict[str, Any]


def _clone_inputs(inputs: list) -> list:
    return [[float(v) for v in gene] if isinstance(gene, list) else [float(gene)] for gene in inputs]


def _set_gene(inputs: list, idx: int, value: float, min_value: float | None = None, max_value: float | None = None) -> None:
    if idx < 0 or idx >= len(inputs):
        return
    if min_value is not None:
        value = max(min_value, value)
    if max_value is not None:
        value = min(max_value, value)
    inputs[idx][0] = float(value)


def _global_base(algorithm: str) -> int:
    return ALGO_LAYOUT.get(algorithm, ALGO_LAYOUT["additive"])["global_base"]


def _num_floors(inputs: list, algorithm: str) -> int:
    gb = _global_base(algorithm)
    if gb >= len(inputs):
        return 1
    return max(1, round(float(inputs[gb][0])))


def _candidate_specs(patch_plan: dict[str, Any]) -> list[CandidateSpec]:
    specs = []
    for c in patch_plan.get("candidates") or []:
        if not isinstance(c, dict):
            continue
        specs.append(CandidateSpec(
            id=str(c.get("id", "candidate")),
            title=str(c.get("title", "수정 후보")),
            intent=str(c.get("intent", "general_review")),
            patch=c.get("patch") if isinstance(c.get("patch"), dict) else {},
        ))
    return specs


def _apply_spec(inputs: list, algorithm: str, spec: CandidateSpec) -> tuple[list, list[str]]:
    out = _clone_inputs(inputs)
    notes: list[str] = []
    gb = _global_base(algorithm)
    idx_floors = gb
    idx_upper = gb + 2
    idx_step = gb + 3
    floors = _num_floors(out, algorithm)

    if spec.intent == "smooth_stepback":
        # Current genome supports one upper tier only. Approximate "multi-step"
        # by starting stepback earlier and moderately shrinking the upper tier.
        _set_gene(out, idx_step, min(0.55, float(out[idx_step][0]) if idx_step < len(out) else 0.55), 0.3, 0.8)
        _set_gene(out, idx_upper, min(0.82, float(out[idx_upper][0]) if idx_upper < len(out) else 0.82), 0.5, 1.0)
        notes.append("현재 genome은 2-tier stepback만 지원하므로 다단 후퇴는 step_fraction/upper_scale 조정으로 근사했습니다.")
    elif spec.intent == "strengthen_podium":
        podium_floors = int(spec.patch.get("podium_floors") or 3)
        step_frac = max(0.3, min(0.8, podium_floors / max(floors, 1)))
        _set_gene(out, idx_step, step_frac, 0.3, 0.8)
        _set_gene(out, idx_upper, min(0.72, float(out[idx_upper][0]) if idx_upper < len(out) else 0.72), 0.5, 1.0)
        notes.append("포디움 강화는 저층 footprint 유지 + 상층부 축소로 근사했습니다.")
    elif spec.intent == "refine_proportion":
        _set_gene(out, idx_upper, min(0.78, float(out[idx_upper][0]) if idx_upper < len(out) else 0.78), 0.5, 1.0)
        _set_gene(out, idx_step, 0.62, 0.3, 0.8)
        notes.append("비례 개선은 상층부 축소와 후퇴 시작층 조정으로 근사했습니다.")
    elif spec.intent == "increase_far":
        _set_gene(out, idx_floors, floors + 1, 1, floors + 3)
        _set_gene(out, idx_upper, min(1.0, (float(out[idx_upper][0]) if idx_upper < len(out) else 0.9) + 0.05), 0.5, 1.0)
        notes.append("용적률 증가는 1개층 증축 + 상층부 축소 완화로 근사했습니다.")
    elif spec.intent == "move_core":
        notes.append("코어 이동은 매스 geometry가 아니라 floor/core planner 단계에서 적용해야 하므로 preview geometry는 원안과 동일합니다.")
    else:
        _set_gene(out, idx_upper, min(0.85, float(out[idx_upper][0]) if idx_upper < len(out) else 0.85), 0.5, 1.0)
        notes.append("일반 리뷰 후보는 보수적 상층부 조정으로 근사했습니다.")

    return out, notes


def _outputs_to_metrics(outputs: list[float], outputs_def: list[dict]) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for i, out_def in enumerate(outputs_def):
        if i < len(outputs):
            metrics[out_def.get("name", f"output_{i}")] = float(outputs[i])
    return metrics


def build_interactive_preview(
    *,
    patch_plan: dict[str, Any],
    selected_design: dict[str, Any],
    site_polygon_geojson: dict[str, Any],
    site_area_m2: float,
    constraints: list[dict[str, Any]] | None = None,
    building_type: str = "공동주택",
    algorithm: str | None = None,
) -> dict[str, Any]:
    """Return geometry/metrics previews for patch candidates."""
    inputs = selected_design.get("inputs") or []
    if not inputs:
        return {"error": "selected_design.inputs is required"}
    if not site_polygon_geojson:
        return {"error": "site_polygon is required"}

    algorithm = algorithm or selected_design.get("algorithm") or "additive"
    site_polygon = geojson_to_polygon(site_polygon_geojson)
    job_spec = build_default_job_spec(site_area_m2, constraints or [], building_type, algorithm)
    outputs_def = job_spec.get("outputs", [])

    previews = []
    for spec in _candidate_specs(patch_plan):
        candidate_inputs, notes = _apply_spec(inputs, algorithm, spec)
        design = Design(_id=0, des_num=0, gen_num=0)
        design.set_inputs(candidate_inputs)
        outputs = evaluate_designs(
            [design],
            site_polygon,
            site_area_m2,
            outputs_def,
            building_type,
            algorithm,
            enable_repair=True,
        )[0]
        design.set_outputs(outputs, outputs_def)
        mass_geojson = design_to_geojson(
            candidate_inputs,
            site_polygon,
            site_area_m2,
            building_type,
            algorithm,
            enable_repair=True,
            outputs_def=outputs_def,
        )
        if mass_geojson:
            mass_geojson["properties"]["design_id"] = selected_design.get("id")
            mass_geojson["properties"]["interactive_candidate_id"] = spec.id
            mass_geojson["properties"]["algorithm"] = algorithm

        previews.append({
            "id": spec.id,
            "title": spec.title,
            "intent": spec.intent,
            "feasible": bool(design.feasible and mass_geojson),
            "penalty": float(design.penalty),
            "inputs": candidate_inputs,
            "outputs": outputs,
            "metrics": _outputs_to_metrics(outputs, outputs_def),
            "mass_geojson": mass_geojson,
            "notes": notes,
        })

    return {
        "mode": "preview",
        "selected_design_id": selected_design.get("id")
        if selected_design.get("id") is not None
        else selected_design.get("design_id"),
        "algorithm": algorithm,
        "building_type": building_type,
        "candidates": previews,
        "notes": [
            "M2 preview: 전체 optimizer 재실행 없이 선택안의 입력값을 보수적으로 조정한 후보입니다.",
            "정북일조 envelope hard 검증은 다음 단계에서 sunlight_envelope 연결 후 강화해야 합니다.",
        ],
    }


__all__ = ["build_interactive_preview"]
