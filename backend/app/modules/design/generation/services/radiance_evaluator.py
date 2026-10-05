"""
A2 — Radiance lite Evaluator (Phase 1, 2026-05-06)

매스 평가 함수 *교체* — 정북일조 기하 검증 → *진짜 광선 추적*.

UDI (Useful Daylight Illuminance) — 연중 100~2000 lux 받는 시간 비율
sDA (spatial Daylight Autonomy) — 300 lux 이상 자연광 받는 면적 비율

상태 (2026-05-06):
    - **인터페이스만 구현**. Radiance 바이너리 + pyradiance/honeybee 미설치.
    - 외부 의존 설치 후 `_radiance_compute_udi_sda()` 구현체로 교체.
    - 현재는 fallback (기존 daylight_score 사용) — 데모/CI 깨지지 않음.

연구 노트: `research/01_PHASE1/A2_radiance_lite.md`

설치 후 활성화 절차:
    1. Radiance 바이너리 설치 (Windows: 별도 인스톨러 또는 WSL2)
    2. `pip install pyradiance` 또는 `pip install honeybee-radiance`
    3. `RADIANCE_AVAILABLE = True` 로 변경
    4. `_radiance_compute_udi_sda()` 실제 구현 채움
"""

import logging
from dataclasses import dataclass

from shapely.geometry import Polygon

from backend.app.modules.design.generation.services.evaluators import Evaluator, EvaluationContext, INFEASIBLE_METRICS, register_evaluator

logger = logging.getLogger(__name__)


# ───────────────────────────────────────────────────────────
# 외부 의존 가용 여부 (False = fallback)
# ───────────────────────────────────────────────────────────
RADIANCE_AVAILABLE = False  # 향후 pyradiance 설치 후 True

try:
    import pyradiance  # type: ignore
    RADIANCE_AVAILABLE = True
except ImportError:
    pyradiance = None


@dataclass
class RadianceConfig:
    """Radiance 시뮬레이션 설정."""
    weather_file: str = "Seoul.epw"  # Seoul ASHRAE/EnergyPlus weather data
    grid_size_m: float = 1.0          # 분석 그리드 (1m 간격)
    target_illuminance_lux: float = 300.0  # sDA threshold
    udi_lower_lux: float = 100.0      # UDI lower bound
    udi_upper_lux: float = 2000.0     # UDI upper bound
    occupied_hours_per_year: int = 3650  # 약 10시간/일 × 365일


def _fallback_udi_sda(footprint: Polygon, num_floors: int, site_area_m2: float) -> tuple[float, float]:
    """
    Radiance 미설치 시 fallback. 기존 mass_evaluator의 daylight_score 로직 활용.

    UDI ≈ open_ratio × perimeter_ratio × stepback_bonus 정도의 proxy.
    sDA ≈ open 영역 비율 proxy.
    """
    import math

    if footprint.is_empty or site_area_m2 < 1.0:
        return 0.0, 0.0

    fp_area = footprint.area
    open_ratio = max(0.0, 1.0 - fp_area / site_area_m2)
    perimeter_ratio = footprint.length / math.sqrt(fp_area) if fp_area > 0 else 0
    perim_norm = min(perimeter_ratio / 8.0, 1.0)

    # UDI proxy: 0.0~1.0
    udi = round(open_ratio * 0.4 + perim_norm * 0.4 + 0.2, 4)

    # sDA proxy: 채광 면적 비율
    sda = round(min(perim_norm * 0.7 + open_ratio * 0.3, 1.0), 4)

    return udi, sda


def _radiance_compute_udi_sda(footprint: Polygon, num_floors: int,
                               floor_height_m: float, config: RadianceConfig) -> tuple[float, float]:
    """
    실제 Radiance 광선 추적 — *현재 미구현*.

    구현 시:
        1. footprint + height → OBJ mesh 변환
        2. Seoul.epw 날씨 데이터 로드
        3. pyradiance.rtrace 또는 honeybee.run 호출
        4. UDI / sDA 계산 후 반환
    """
    if not RADIANCE_AVAILABLE:
        raise NotImplementedError(
            "Radiance not installed. Install pyradiance or honeybee-radiance."
        )
    # TODO: 실제 광선 추적 구현
    raise NotImplementedError("Radiance 실제 평가 미구현 — A2 follow-up PR")


# ───────────────────────────────────────────────────────────
# RadianceEvaluator
# ───────────────────────────────────────────────────────────

class RadianceEvaluator(Evaluator):
    """
    Radiance 기반 일조 평가 (UDI/sDA).

    Radiance 미설치 시 fallback (기존 기하 score).
    설치 후엔 _radiance_compute_udi_sda 사용.
    """

    name = "radiance"

    def __init__(self, config: RadianceConfig | None = None):
        self.config = config or RadianceConfig()
        self.using_fallback = not RADIANCE_AVAILABLE
        if self.using_fallback:
            logger.warning(
                "RadianceEvaluator: pyradiance 미설치 — fallback (기하 proxy) 사용. "
                "research/01_PHASE1/A2_radiance_lite.md 참조."
            )

    def evaluate(self, gene_inputs: list, context: EvaluationContext) -> dict:
        """
        매스 평가. Radiance 결과를 daylight_score 자리에 채움.
        나머지 metric은 BasicGeometricEvaluator 호출 (조합형).
        """
        from backend.app.modules.design.generation.services.evaluators import BasicGeometricEvaluator
        # 기본 metric은 기하 평가에서 가져오고
        base = BasicGeometricEvaluator()
        metrics = base.evaluate(gene_inputs, context)

        # daylight_score 만 Radiance/fallback으로 교체
        from backend.app.modules.design.generation.services.mass_evaluator import BUILDERS, _build_mass_polygon_freeform, _global_idx, get_floor_height
        builder = BUILDERS.get(context.algorithm, _build_mass_polygon_freeform)
        building, _ = builder(gene_inputs, context.site_utm)
        if building is None or building.is_empty:
            return metrics

        footprint = building.intersection(context.site_utm)
        if footprint.is_empty:
            return metrics

        gb = _global_idx(context.algorithm, 0)
        num_floors = max(1, round(gene_inputs[gb][0]))
        floor_height = get_floor_height(context.building_type)

        if self.using_fallback:
            udi, sda = _fallback_udi_sda(footprint, num_floors, context.site_area_m2)
        else:
            udi, sda = _radiance_compute_udi_sda(footprint, num_floors, floor_height, self.config)

        # Radiance 결과를 daylight_score (0~100) 로 변환
        # daylight_score = (UDI 가중치 0.6) + (sDA 가중치 0.4) × 100
        metrics["daylight_score"] = round((udi * 0.6 + sda * 0.4) * 100, 2)
        # 추가 metric (선택적)
        metrics["udi"] = udi
        metrics["sda"] = sda

        return metrics


# Auto-register
register_evaluator("radiance", RadianceEvaluator)


__all__ = [
    "RadianceConfig",
    "RadianceEvaluator",
    "RADIANCE_AVAILABLE",
]
