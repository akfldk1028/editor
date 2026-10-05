"""
A6 — Repair Operator (Hard Constraint 강제)

Phase 1 작업. envelope/BCR/FAR/높이 위반 매스를 *자동 수정*해
penalty=0 feasible 매스만 GA Pareto에 들어가게 한다.

플렉시티 광고처럼 *envelope 안에 무조건 fit* 되도록 강제.

전략 (단순 1차 repair):
    1. Site boundary clip — footprint를 site 안으로
    2. Adjacent setback inward buffer — 이격선 안으로
    3. BCR clamp — footprint 면적 한도 초과 시 centroid scale-down
    4. FAR clamp — floor area 한도 초과 시 층수 감소
    5. Height clamp — 높이 한도 초과 시 층수 cap
    6. North sunlight setback (단순화) — 북측 1.5m 후퇴 + 상층 step-back

LOCKED envelope (`land/services/envelopes/sunlight.py`)을 *직접 호출하지 않음*
(frontend renderer 계약과 충돌). 단순 footprint 후처리만.

향후 Phase 3 PGDM 통합 시 본 모듈은 *fallback*.
"""

import logging
import math
from dataclasses import dataclass

from pyproj import Transformer
from shapely.geometry import Polygon, MultiPolygon, Polygon as ShPolygon
from shapely.affinity import scale as shapely_scale, translate as shapely_translate
from shapely.ops import transform as shp_transform

logger = logging.getLogger(__name__)

# Phase B (2026-05-08) — module-level transformer (per-call import overhead 제거).
# NSGA-II per-design call에서 5000+ 호출되므로 함수 안 import 비용 큼.
_WGS_TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:32652", always_xy=True)


@dataclass
class RegulationLimits:
    """A6 repair에 필요한 핵심 한도."""
    bcr_limit_pct: float = 80.0      # 건폐율 (%)
    far_limit_pct: float = 1300.0    # 용적률 (%)
    height_limit_m: float = 50.0     # 높이 (m)
    adjacent_setback_m: float = 1.0  # 인접대지 이격 (m)
    road_setback_m: float = 3.0      # 도로 후퇴 (건축선, m) — exp003 추가
    north_setback_m: float = 1.5     # 정북 일조 base setback (m, §86①제1호)
    floor_height_m: float = 3.0      # 1개 층 높이


@dataclass
class RepairReport:
    """repair 결과 보고."""
    repaired: bool
    actions: list[str]
    bcr_before: float
    bcr_after: float
    far_before: float
    far_after: float
    floors_before: int
    floors_after: int


def repair_footprint(
    footprint: Polygon,
    site_utm: Polygon,
    limits: RegulationLimits,
) -> tuple[Polygon | None, RepairReport]:
    """
    Footprint 단계 repair.

    Args:
        footprint: GA가 생성한 매스 footprint (UTM Polygon)
        site_utm: 부지 polygon (UTM)
        limits: 법규 한도

    Returns:
        (repaired_footprint, report)
        repaired_footprint: feasible 매스의 footprint. None이면 repair 실패.
    """
    actions = []
    bcr_before = 0.0
    bcr_after = 0.0

    if footprint is None or footprint.is_empty:
        return None, RepairReport(False, ["empty"], 0, 0, 0, 0, 0, 0)

    site_area = site_utm.area
    if site_area < 1.0:
        return None, RepairReport(False, ["site_too_small"], 0, 0, 0, 0, 0, 0)

    bcr_before = footprint.area / site_area * 100

    # 1. MultiPolygon → 가장 큰 부분만
    if isinstance(footprint, MultiPolygon):
        footprint = max(footprint.geoms, key=lambda g: g.area)
        actions.append("multipolygon_to_largest")

    # 2. Site boundary clip
    if not site_utm.contains(footprint):
        clipped = footprint.intersection(site_utm)
        if clipped.is_empty or clipped.area < 1.0:
            return None, RepairReport(False, actions + ["site_clip_empty"],
                                      bcr_before, 0, 0, 0, 0, 0)
        if isinstance(clipped, MultiPolygon):
            clipped = max(clipped.geoms, key=lambda g: g.area)
        footprint = clipped
        actions.append("site_clip")

    # 3. Setback inward buffer (boundary 기준 — 도로/인접 중 *큰 값* 적용 = 보수적)
    # exp003 발견: 분당 케이스에서 road_setback=3m > adjacent=1m. 1m만 적용 시 0% feasible.
    effective_setback = max(limits.adjacent_setback_m, limits.road_setback_m)
    if effective_setback > 0:
        inward = site_utm.buffer(-effective_setback)
        if not inward.is_empty and inward.area > 1.0:
            if not inward.contains(footprint):
                clipped = footprint.intersection(inward)
                if not clipped.is_empty and clipped.area > 1.0:
                    if isinstance(clipped, MultiPolygon):
                        clipped = max(clipped.geoms, key=lambda g: g.area)
                    footprint = clipped
                    actions.append(f"setback_clip_{effective_setback}m")

    # 4. North sunlight base setback (§86①제1호) — 단순화
    if limits.north_setback_m > 0:
        # 북쪽 (y_max) 변에서 1.5m 안쪽으로 자름
        # site의 북쪽 기준
        minx, miny, maxx, maxy = site_utm.bounds
        north_clip_y = maxy - limits.north_setback_m
        if north_clip_y > miny:
            # footprint y >= north_clip_y 영역 잘라냄
            from shapely.geometry import box as shapely_box
            keep_box = shapely_box(minx - 1, miny - 1, maxx + 1, north_clip_y)
            clipped = footprint.intersection(keep_box)
            if not clipped.is_empty and clipped.area > 1.0:
                if isinstance(clipped, MultiPolygon):
                    clipped = max(clipped.geoms, key=lambda g: g.area)
                if clipped.area < footprint.area * 0.99:  # 실제로 잘린 경우만
                    footprint = clipped
                    actions.append(f"north_setback_{limits.north_setback_m}m")

    # 5. BCR clamp — footprint 면적 한도 초과 시 centroid 기준 scale-down
    # Code review fix (2026-05-06): scaled.intersection(site_utm) 만 했는데, 그러면 setback
    # boundary 가 무시되어 BCR 통과해도 setback 위반 가능. inward (setback) 와 site 모두 만족하는
    # 영역으로 clip + 최대 3 iter guard loop.
    inward_for_clip = site_utm.buffer(-effective_setback) if effective_setback > 0 else site_utm
    if inward_for_clip.is_empty:
        inward_for_clip = site_utm  # setback 너무 커서 inward 비면 site로 fallback
    bcr_after = footprint.area / site_area * 100
    for _iter in range(3):
        if bcr_after <= limits.bcr_limit_pct:
            break
        scale_factor = math.sqrt(limits.bcr_limit_pct / bcr_after) * 0.99
        scaled = shapely_scale(footprint, xfact=scale_factor, yfact=scale_factor, origin='centroid')
        scaled = scaled.intersection(inward_for_clip)
        if scaled.is_empty or scaled.area < 1.0:
            break
        if isinstance(scaled, MultiPolygon):
            scaled = max(scaled.geoms, key=lambda g: g.area)
        footprint = scaled
        bcr_after = footprint.area / site_area * 100
        actions.append(f"bcr_clamp_iter{_iter+1}_to_{round(bcr_after, 1)}")

    return footprint, RepairReport(
        repaired=len(actions) > 0,
        actions=actions,
        bcr_before=round(bcr_before, 2),
        bcr_after=round(bcr_after, 2),
        far_before=0,  # FAR/높이는 repair_floors에서 처리
        far_after=0,
        floors_before=0,
        floors_after=0,
    )


def repair_floors(
    footprint: Polygon,
    site_utm: Polygon,
    num_floors: int,
    limits: RegulationLimits,
) -> tuple[int, RepairReport]:
    """
    층수 단계 repair (FAR/높이 hard cap).

    Returns:
        (repaired_num_floors, report)
    """
    actions = []
    site_area = site_utm.area
    floors_before = num_floors

    # 1. Height cap
    max_floors_by_height = max(1, int(limits.height_limit_m / limits.floor_height_m))
    if num_floors > max_floors_by_height:
        num_floors = max_floors_by_height
        actions.append(f"height_cap_to_{num_floors}f")

    # 2. FAR cap
    floor_area = footprint.area * num_floors
    far_before = floor_area / site_area * 100 if site_area > 0 else 9999
    if far_before > limits.far_limit_pct:
        # 층수 감소
        max_floors_by_far = max(1, int(limits.far_limit_pct / 100 * site_area / footprint.area))
        num_floors = min(num_floors, max_floors_by_far)
        actions.append(f"far_cap_to_{num_floors}f")
    far_after = footprint.area * num_floors / site_area * 100 if site_area > 0 else 0

    return num_floors, RepairReport(
        repaired=len(actions) > 0,
        actions=actions,
        bcr_before=0, bcr_after=0,
        far_before=round(far_before, 2),
        far_after=round(far_after, 2),
        floors_before=floors_before,
        floors_after=num_floors,
    )


def clip_to_sunlight_envelope(
    footprint: Polygon,
    sunlight_envelope: dict | None,
) -> tuple[Polygon, list[str]]:
    """
    Phase B (2026-05-08) — 정북 일조 envelope inner polygon으로 footprint clip.

    sunlight_envelope.slanted_polygons[0].corners는 LOCKED SPEC `parcel.buffer(-1.5m)`
    inner polygon의 외곽선 (WGS84). UTM 변환 후 footprint와 intersection.

    매스가 §86①제1호 "1.5m 이격 내부" 영역 안에서만 솟아오르도록 강제. H>10m
    부분의 slope clip은 frontend mass_renderer가 per-floor로 별도 처리 (Phase B 후속).

    Args:
        footprint: UTM Polygon
        sunlight_envelope: backend 출력 dict 또는 None

    Returns:
        (clipped_footprint, actions)
        envelope 없거나 잘 안되면 footprint 원본.
    """
    if sunlight_envelope is None:
        return footprint, []
    slanted = sunlight_envelope.get("slanted_polygons") or []
    if not slanted:
        return footprint, []
    corners_wgs = slanted[0].get("corners") or []
    if len(corners_wgs) < 3:
        return footprint, []
    try:
        ring_wgs = [(c[0], c[1]) for c in corners_wgs]
        if ring_wgs[0] != ring_wgs[-1]:
            ring_wgs.append(ring_wgs[0])
        envelope_wgs = ShPolygon(ring_wgs)
        envelope_utm = shp_transform(_WGS_TO_UTM.transform, envelope_wgs)
        if envelope_utm.is_empty or envelope_utm.area < 1.0:
            return footprint, []
        if not envelope_utm.contains(footprint):
            clipped = footprint.intersection(envelope_utm)
            if clipped.is_empty or clipped.area < 1.0:
                return footprint, []
            if isinstance(clipped, MultiPolygon):
                clipped = max(clipped.geoms, key=lambda g: g.area)
            return clipped, [f"sunlight_envelope_clip_to_{round(envelope_utm.area, 1)}m2"]
        return footprint, []
    except Exception as e:
        logger.warning(f"sunlight envelope clip failed: {e}")
        return footprint, []


def _sunlight_height_cap_m(sunlight_envelope: dict | None) -> float | None:
    """Conservative height cap from the lowest 3D sunlight envelope corner.

    The current mass model stores one footprint plus optional two-tier stepback,
    not per-floor clipped polygons. Until full per-floor projection exists, a
    mass must stay below the lowest envelope height to avoid visibly piercing the
    sloped §86 surface.
    """
    if sunlight_envelope is None:
        return None
    heights = []
    for poly in sunlight_envelope.get("slanted_polygons") or []:
        for corner in poly.get("corners") or []:
            if isinstance(corner, (list, tuple)) and len(corner) >= 3:
                try:
                    h = float(corner[2])
                except (TypeError, ValueError):
                    continue
                if h > 0:
                    heights.append(h)
    if not heights:
        return None
    return min(heights)


def repair_design(
    footprint: Polygon,
    site_utm: Polygon,
    num_floors: int,
    limits: RegulationLimits,
    sunlight_envelope: dict | None = None,
) -> tuple[Polygon | None, int, list[str]]:
    """
    Footprint + 층수 통합 repair.

    Args:
        sunlight_envelope (Phase B 2026-05-08, optional): backend 출력 envelope dict.
            제공시 §86①제1호 inner polygon으로 footprint clip 추가.

    Returns:
        (repaired_footprint, repaired_num_floors, all_actions)
        repaired_footprint=None이면 unfeasible (repair 실패).
    """
    repaired_fp, fp_report = repair_footprint(footprint, site_utm, limits)
    if repaired_fp is None:
        return None, num_floors, fp_report.actions

    # Phase B — sunlight envelope inner polygon clip
    repaired_fp, sunlight_actions = clip_to_sunlight_envelope(repaired_fp, sunlight_envelope)

    repaired_floors, floors_report = repair_floors(repaired_fp, site_utm, num_floors, limits)
    height_cap = _sunlight_height_cap_m(sunlight_envelope)
    height_actions = []
    if height_cap is not None:
        max_floors_by_sunlight = max(1, int(height_cap / max(limits.floor_height_m, 0.1)))
        if repaired_floors > max_floors_by_sunlight:
            repaired_floors = max_floors_by_sunlight
            height_actions.append(f"sunlight_height_cap_to_{repaired_floors}f")

    return repaired_fp, repaired_floors, fp_report.actions + sunlight_actions + floors_report.actions + height_actions


__all__ = [
    "RegulationLimits",
    "RepairReport",
    "repair_footprint",
    "repair_floors",
    "repair_design",
    "_sunlight_height_cap_m",
]
