"""
Datum 6 케이스 dispatcher.

input(parcel + 선택적 road centerline + 선택적 §86 neighbor flag) 에서
어느 §119/§86 케이스가 적용되는지 판단 + calculator 호출.

우선순위 (가장 엄격한 규제 = 가장 datum을 올리는 것):
    1. §86 정북인접지 평균 (apply_86_neighbor_avg=True + neighbor 제공시)
    2. §119① 5호 도로 접지 (road_centerline 제공시)
       - 대지 > 도로 → SITE_ABOVE_ROAD (1/2 raise)
       - 그 외 → ROAD_FLAT / ROAD_SLOPED
    3. §119② 대지 자체 (default)
       - 변화 < 0.5m → FLAT
       - ≤ 3m → SLOPE_LE3M
       - > 3m → SLOPE_GT3M (분할 stub)

Failure handling
----------------
- elevation_api 실패 (ElevationFetchError) → DatumResult.elevation_source="failed"
  + elevation_m=0.0 + notes 에 사유. caller(envelope)는 source 확인 후 datum 미적용 결정 가능.
- 빈 polygon (calculator.parcel_datum_119 ValueError) → caller 책임 (정상적으로 raise).

DoS / abuse guard
-----------------
- MAX_PARCEL_VERTICES: 폴리곤 vertex 너무 많으면 reject (HTTP 호출 폭주 방지).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from dataclasses import field

from shapely.geometry import LineString, Polygon

from backend.app.modules.land.reference import config as land_config
from backend.app.modules.land.reference.services.datum import calculator
from backend.app.modules.land.reference.services.datum.elevation_api import ElevationFetchError


class DatumCase(str, Enum):
    FLAT = "flat"
    SLOPE_LE3M = "slope_le3m"
    SLOPE_GT3M = "slope_gt3m"
    ROAD_FLAT = "road_flat"
    ROAD_SLOPED = "road_sloped"
    SITE_ABOVE_ROAD = "site_above_road"
    NEIGHBOR_AVG_86 = "neighbor_avg_86"


# basis 라벨 (DatumResult.basis 용)
# SLOPE_GT3M은 DEM 외곽 표고 profile 기반 3m band datum을 산출한다.
# 실제 등고선 polygon clipping은 별도 단계로 남아 있으므로 basis에 profile을 명시.
_BASIS_LABEL = {
    DatumCase.FLAT: "ground_flat",
    DatumCase.SLOPE_LE3M: "ground_weighted_avg",
    DatumCase.SLOPE_GT3M: "ground_split_3m_profile",
    DatumCase.ROAD_FLAT: "road_centerline",
    DatumCase.ROAD_SLOPED: "road_centerline_weighted_avg",
    DatumCase.SITE_ABOVE_ROAD: "site_above_road_half_raise",
    DatumCase.NEIGHBOR_AVG_86: "neighbor_avg_86",
}

# 케이스 결정 임계값 (§119② 본래 정의로 복귀, 2026-05-09)
#
# 라이브 검증 (4 도곡/개포/대치 PNU, NGII 5m 자체 호스팅):
#   - 도곡동 467-3 (5 vert): NGII spread 0m → FLAT 정확
#   - 도곡동 960 (29 vert):  NGII 2.44m / OM 4.00m → 90m noise 61% 감소
#   - 개포동 660-11 (산기슭): NGII 11.3m / OM 11.0m → SLOPE_GT3M 정확
#   - 대치동 1028 (12 vert):  NGII 0m / OM 8.0m → 90m noise 100% 흡수
#
# NGII 1:5,000 5m DEM (수치지형도 등고선 + 표고점 TIN 보간) 도입 후 90m DEM 격자
# 노이즈 사라짐. §119② 본래 정의 (단서 3m) 그대로 복귀 가능.
# 이전 임계값 (FLAT 2.0, SLOPE_3M 8.0) = 90m DEM 노이즈 수용용 임시값. 폐기.
FLAT_VARIANCE_THRESHOLD_M = 0.5    # §119②: 변동 < 0.5m 사실상 평탄
SLOPE_3M_THRESHOLD_M = 3.0         # §119② 단서: max-min > 3m → SLOPE_GT3M (분할 대상)
ROAD_SLOPE_THRESHOLD_M = 0.5       # 도로 노면 평탄 임계값 (§119① 5호 가목 단서)

# DoS guard — 폴리곤 외곽 vertex 수 상한 (HTTP 호출 폭주 방지)
MAX_PARCEL_VERTICES = 500


# elevation_source 값 (DatumResult.elevation_source 용)
ELEV_SOURCE_OPEN_METEO = "open_meteo"
ELEV_SOURCE_FAILED = "failed"


@dataclass(frozen=True)
class DatumContext:
    """compute_datum_elevation 입력 컨텍스트."""
    parcel_wgs: Polygon
    road_centerline_wgs: LineString | None = None
    neighbor_parcel_wgs: Polygon | None = None
    apply_86_neighbor_avg: bool = False
    apply_road_datum: bool = False


@dataclass(frozen=True)
class DatumResult:
    """compute_datum_elevation 출력. envelope 등에서 H=0 기준으로 사용.

    elevation_source가 "failed"면 elevation_m은 신뢰 불가 (0.0 fallback).
    envelope 사용시 source 확인 후 datum 적용 여부 결정.
    """
    elevation_m: float
    case: DatumCase
    basis: str
    # 동적 default: 현재 ELEVATION_PROVIDER 값 사용 (open_meteo / copernicus_glo30 / ngii_lidar_1m)
    elevation_source: str = field(default_factory=lambda: land_config.ELEVATION_PROVIDER)
    parcel_segments: list[dict] | None = None
    road_samples: list[dict] | None = None
    neighbor_segments: list[dict] | None = None
    parcel_datum_m: float | None = None
    road_datum_m: float | None = None
    neighbor_datum_m: float | None = None
    neighbor_avg_datum_m: float | None = None
    split_polygons: list[dict] | None = None  # §119② 단서: 3m band datum metadata
    split_bands: list[dict] | None = None      # 명시적 alias: 실제 polygon 아님
    notes: list[str] | None = None


def _validate_polygon(p: Polygon, label: str) -> None:
    """DoS guard: vertex 수 상한 체크."""
    n = len(p.exterior.coords) if hasattr(p.exterior, "coords") else 0
    if n > MAX_PARCEL_VERTICES:
        raise ValueError(
            f"{label} has {n} vertices > MAX_PARCEL_VERTICES={MAX_PARCEL_VERTICES}. "
            "DoS guard: simplify polygon before passing to compute_datum_elevation."
        )


def _failed_result(reason: str) -> DatumResult:
    """elevation fetch 전체 실패시 fallback DatumResult."""
    return DatumResult(
        elevation_m=0.0,
        case=DatumCase.FLAT,
        basis="elevation_fetch_failed",
        elevation_source=ELEV_SOURCE_FAILED,
        notes=[
            f"Open-Meteo fetch 실패: {reason}. datum=0.0 fallback. "
            "envelope 사용시 source='failed' 확인하고 datum 미적용 권장."
        ],
    )


def compute_datum_elevation(ctx: DatumContext) -> DatumResult:
    """
    6 케이스 dispatcher. 입력 ctx의 flag/geometry로 case를 자동 결정.

    Args:
        ctx: parcel + 선택적 road/neighbor context.

    Returns:
        DatumResult. elevation fetch 실패시 elevation_source="failed" + notes.

    Raises:
        ValueError: ctx.parcel_wgs 가 무효 (vertex 0개 또는 MAX 초과).
    """
    _validate_polygon(ctx.parcel_wgs, "ctx.parcel_wgs")
    if ctx.neighbor_parcel_wgs is not None:
        _validate_polygon(ctx.neighbor_parcel_wgs, "ctx.neighbor_parcel_wgs")

    notes: list[str] = []

    # 항상 parcel datum 계산 (다른 케이스도 비교용)
    try:
        parcel_datum_m, parcel_segments = calculator.parcel_datum_119(ctx.parcel_wgs)
    except ElevationFetchError as e:
        return _failed_result(str(e))

    parcel_elevs = [s["midpoint_elev_m"] for s in parcel_segments]
    parcel_diff = (max(parcel_elevs) - min(parcel_elevs)) if parcel_elevs else 0.0

    neighbor_datum_m = None
    neighbor_segments = None
    if ctx.neighbor_parcel_wgs is not None:
        try:
            neighbor_datum_m, neighbor_segments = calculator.parcel_datum_119(ctx.neighbor_parcel_wgs)
        except ElevationFetchError as e:
            notes.append(f"neighbor parcel datum failed: {e}")

    # 1. §86 정북인접지 평균
    if ctx.apply_86_neighbor_avg:
        if neighbor_datum_m is None:
            notes.append(
                "apply_86_neighbor_avg=True지만 neighbor_parcel_wgs 없음 — "
                "§86 신청 무시, 일반 §119 처리로 fallback."
            )
        else:
            elevation = calculator.neighbor_avg_datum_86(parcel_datum_m, neighbor_datum_m)
            if ctx.road_centerline_wgs is not None:
                notes.append("§86 정북인접지 평균 적용 — road_centerline 무시됨.")
            return DatumResult(
                elevation_m=elevation,
                case=DatumCase.NEIGHBOR_AVG_86,
                basis=_BASIS_LABEL[DatumCase.NEIGHBOR_AVG_86],
                parcel_segments=parcel_segments,
                neighbor_segments=neighbor_segments,
                parcel_datum_m=parcel_datum_m,
                neighbor_datum_m=neighbor_datum_m,
                notes=notes,
            )

    # 2. §119① 5호 도로 접지. 기본은 metadata만 계산하고 parcel datum case를 유지한다.
    road_datum_m = None
    road_samples = None
    road_case = None
    if ctx.road_centerline_wgs is not None:
        try:
            road_datum_m, road_samples = calculator.road_datum_119(ctx.road_centerline_wgs)
        except ElevationFetchError as e:
            notes.append(f"road centerline datum failed: {e}")
            road_datum_m = None
            road_samples = None
        if road_datum_m is None or road_samples is None:
            road_elevs = []
        else:
            road_elevs = [s["elev_m"] for s in road_samples]
        road_diff = (max(road_elevs) - min(road_elevs)) if road_elevs else 0.0

        # 대지 > 도로
        if road_datum_m is not None and parcel_datum_m > road_datum_m + 0.1:
            road_case = DatumCase.SITE_ABOVE_ROAD
            elevation = calculator.site_above_road_119(parcel_datum_m, road_datum_m)
            if ctx.apply_road_datum:
                return DatumResult(
                    elevation_m=elevation,
                    case=DatumCase.SITE_ABOVE_ROAD,
                    basis=_BASIS_LABEL[DatumCase.SITE_ABOVE_ROAD],
                    parcel_segments=parcel_segments,
                    road_samples=road_samples,
                    neighbor_segments=neighbor_segments,
                    parcel_datum_m=parcel_datum_m,
                    road_datum_m=road_datum_m,
                    neighbor_datum_m=neighbor_datum_m,
                    neighbor_avg_datum_m=(
                        calculator.neighbor_avg_datum_86(parcel_datum_m, neighbor_datum_m)
                        if neighbor_datum_m is not None else None
                    ),
                    notes=notes,
                )

        # 도로 노면 경사 여부
        road_case = road_case or (
            DatumCase.ROAD_SLOPED if road_diff >= ROAD_SLOPE_THRESHOLD_M
            else DatumCase.ROAD_FLAT
        )
        if ctx.apply_road_datum and road_datum_m is not None:
            return DatumResult(
                elevation_m=road_datum_m,
                case=road_case,
                basis=_BASIS_LABEL[road_case],
                parcel_segments=parcel_segments,
                road_samples=road_samples,
                neighbor_segments=neighbor_segments,
                parcel_datum_m=parcel_datum_m,
                road_datum_m=road_datum_m,
                neighbor_datum_m=neighbor_datum_m,
                neighbor_avg_datum_m=(
                    calculator.neighbor_avg_datum_86(parcel_datum_m, neighbor_datum_m)
                    if neighbor_datum_m is not None else None
                ),
                notes=notes,
            )

    # 3. §119② 대지 자체 (single return for parcel-only)
    if parcel_diff < FLAT_VARIANCE_THRESHOLD_M:
        case = DatumCase.FLAT
    elif parcel_diff <= SLOPE_3M_THRESHOLD_M:
        case = DatumCase.SLOPE_LE3M
    else:
        case = DatumCase.SLOPE_GT3M
        notes.append(
            f"고저차 {parcel_diff:.2f}m > 3m: §119② 단서 적용. "
            "DEM 외곽 표고 profile을 3m band로 분할해 split_polygons에 노출. "
            "실제 등고선 면 polygon clipping은 후속 구현 필요."
        )

    split = calculator.split_3m_segments(ctx.parcel_wgs) if case == DatumCase.SLOPE_GT3M else None

    return DatumResult(
        elevation_m=parcel_datum_m,
        case=case,
        basis=_BASIS_LABEL[case],
        parcel_segments=parcel_segments,
        parcel_datum_m=parcel_datum_m,
        road_samples=road_samples,
        neighbor_segments=neighbor_segments,
        road_datum_m=road_datum_m,
        neighbor_datum_m=neighbor_datum_m,
        neighbor_avg_datum_m=(
            calculator.neighbor_avg_datum_86(parcel_datum_m, neighbor_datum_m)
            if neighbor_datum_m is not None else None
        ),
        split_polygons=split,
        split_bands=split,
        notes=notes,
    )
