"""
A4 — Evaluator 통일 인터페이스 (Phase 1, 2026-05-06)

매스 평가의 *추상 클래스* 정의. 향후 RadianceEvaluator(A2),
SurrogateEvaluator(B1) 등이 동일 인터페이스로 plug-in 가능.

기존 `mass_evaluator.evaluate_designs()` 함수는 *유지* — 본 모듈은
*추가 layer*. 점진적 전환 가능.

사용 예:
    from design.services.evaluators import BasicGeometricEvaluator
    evaluator = BasicGeometricEvaluator(building_type='공동주택', algorithm='additive')
    metrics = evaluator.evaluate(footprint, site_utm, site_area_m2)
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from shapely.geometry import Polygon

logger = logging.getLogger(__name__)


# ───────────────────────────────────────────────────────────
# Standard Metrics 형식 (모든 Evaluator가 반환해야 하는 7-키)
# ───────────────────────────────────────────────────────────

DEFAULT_METRIC_KEYS = (
    "floor_area",
    "daylight_score",
    "bcr",
    "far",
    "height",
    "min_setback",
    "open_pct",
)

INFEASIBLE_METRICS = {
    "floor_area": 0.0,
    "daylight_score": 0.0,
    "bcr": 100.0,
    "far": 100.0,
    "height": 0.0,
    "min_setback": 0.0,
    "open_pct": 0.0,
}


@dataclass
class EvaluationContext:
    """평가에 필요한 site/building 정보."""
    site_utm: Polygon
    site_area_m2: float
    building_type: str = "공동주택"
    algorithm: str = "additive"
    enable_repair: bool = False
    repair_limits: object | None = None  # RegulationLimits | None
    extras: dict = field(default_factory=dict)


# ───────────────────────────────────────────────────────────
# Base Class
# ───────────────────────────────────────────────────────────

class Evaluator(ABC):
    """매스 평가 추상 클래스. 모든 evaluator는 evaluate()를 구현."""

    name: str = "abstract"

    @abstractmethod
    def evaluate(self, gene_inputs: list, context: EvaluationContext) -> dict:
        """
        매스 한 개 평가.

        Args:
            gene_inputs: Design.get_inputs() — list of [value] lists (29-D for additive)
            context: site/algorithm/repair_limits 등

        Returns:
            dict with DEFAULT_METRIC_KEYS keys at minimum.
        """
        raise NotImplementedError

    def evaluate_batch(self, designs: list, context: EvaluationContext) -> list[dict]:
        """배치 평가. 기본 구현은 단순 loop. Surrogate 등은 override 가능."""
        return [self.evaluate(d.get_inputs(), context) for d in designs]


# ───────────────────────────────────────────────────────────
# BasicGeometricEvaluator — 현재 mass_evaluator.py wrap
# ───────────────────────────────────────────────────────────

class BasicGeometricEvaluator(Evaluator):
    """
    현재 시스템의 기하 기반 평가 wrap.

    mass_evaluator._compute_metrics() 호출 — Shapely Polygon 기반.
    Phase 1에서 default. Phase 2 SurrogateEvaluator로 대체 가능.
    """

    name = "basic_geometric"

    def evaluate(self, gene_inputs: list, context: EvaluationContext) -> dict:
        from backend.app.modules.design.generation.services.mass_evaluator import _compute_metrics
        return _compute_metrics(
            gene_inputs,
            context.site_utm,
            context.site_area_m2,
            building_type=context.building_type,
            algorithm=context.algorithm,
            enable_repair=context.enable_repair,
            repair_limits=context.repair_limits,
        )


# ───────────────────────────────────────────────────────────
# Registry — 동적 evaluator 선택
# ───────────────────────────────────────────────────────────

_EVALUATOR_REGISTRY: dict[str, type[Evaluator]] = {
    "basic": BasicGeometricEvaluator,
    "basic_geometric": BasicGeometricEvaluator,
}


def register_evaluator(name: str, cls: type[Evaluator]) -> None:
    """새 Evaluator 등록 (RadianceEvaluator, SurrogateEvaluator 등)."""
    _EVALUATOR_REGISTRY[name] = cls
    logger.info(f"Registered evaluator: {name}")


def get_evaluator(name: str = "basic") -> Evaluator:
    """이름으로 Evaluator 인스턴스 생성."""
    cls = _EVALUATOR_REGISTRY.get(name, BasicGeometricEvaluator)
    return cls()


__all__ = [
    "DEFAULT_METRIC_KEYS",
    "INFEASIBLE_METRICS",
    "EvaluationContext",
    "Evaluator",
    "BasicGeometricEvaluator",
    "register_evaluator",
    "get_evaluator",
]
