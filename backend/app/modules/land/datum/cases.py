from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass, replace
from enum import Enum
from shapely.geometry import LineString, Polygon
from backend.app.adapters.elevation import ElevationFetchError
from .calculator import DatumCalculator
from .settings import DatumSettings


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
    """Absolute datum result; failed elevation is None, never an assumed zero.

    Optional road/neighbor failures retain the valid parcel result with notes.
    """
    elevation_m: float | None
    case: DatumCase
    basis: str
    elevation_source: str = 'unknown'
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
    provenance: dict | None = None


def _validate_polygon(p: Polygon, label: str) -> None:
    """DoS guard: vertex 수 상한 체크."""
    if not isinstance(p, Polygon) or p.is_empty or not p.is_valid:
        raise ValueError(f"{label} must be a valid nonempty Polygon")
    n = len(p.exterior.coords)
    if n > MAX_PARCEL_VERTICES:
        raise ValueError(
            f"{label} has {n} vertices > MAX_PARCEL_VERTICES={MAX_PARCEL_VERTICES}. "
            "DoS guard: simplify polygon before passing to compute_datum_elevation."
        )


def _failed_result(reason: str) -> DatumResult:
    """elevation fetch 전체 실패시 fallback DatumResult."""
    return DatumResult(
        elevation_m=None,
        case=DatumCase.FLAT,
        basis="elevation_fetch_failed",
        elevation_source=ELEV_SOURCE_FAILED,
        notes=['Elevation data unavailable; absolute datum was not applied'],
    )


def _compute(ctx: DatumContext, calculator: DatumCalculator) -> DatumResult:
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
            notes.append("neighbor parcel datum unavailable")

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
            notes.append("road centerline datum unavailable")
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


class DatumService:
    def __init__(self, provider, settings=None):
        self.provider = provider
        self.settings = settings if settings is not None else DatumSettings()

    def compute(self, ctx: DatumContext) -> DatumResult:
        calculator = DatumCalculator(self.provider.fetch, self.settings)
        try:
            result = _compute(ctx, calculator)
        except ElevationFetchError:
            result = _failed_result('elevation unavailable')
        provenance = deepcopy(self.provider.provenance)
        if result.elevation_source == 'failed':
            return replace(result, provenance=provenance)
        source = provenance.get('actual_provider') or 'unknown'
        return replace(result, elevation_source=source, provenance=provenance)
