"""
B6 — Core Planner (Phase 2)

원리 (Principle):
    각 매스에 *서비스 코어* (엘리베이터 + 계단 + 화장실) 위치를 자동 배치.

    실 건축 설계의 *5-10% 면적* 이 코어. 동선 효율 = 1) 모든 평면에서 코어까지 거리 ↓,
    2) 코어가 외부 노출되지 않음 (내부 위치), 3) typology 별 적절한 위치.

배치 휴리스틱 (typology별):
    - additive / subtractive / grid: footprint *centroid* 근처 (단순한 형태)
    - tower_podium: tower 부분 centroid (podium 코어 별도 처리)
    - lshape / cross: 두 wing 의 *교차점* (중심 효율)
    - ushape / courtyard: 한쪽 wing 안쪽 (마당 침범 X)
    - radial: 정중앙 (방사 sector 의 anchor)
    - hshape: 가운데 bridge

코어 사이즈 (default):
    - 4m × 4m 정사각형 (중규모 building)
    - 면적 16m² (= 약 1세대 면적과 같은 작은 비율)
    - 사용자 요청 시 6×6 (대규모) / 3×3 (소규모) 조정 가능

검증:
    - 코어가 footprint 안에 *완전히 포함* 되는지
    - footprint boundary 까지 *최소 거리* ≥ 1m (안전 마진)
"""

import logging
import math
from dataclasses import dataclass, field

from shapely.geometry import Polygon, Point, box as shapely_box
from shapely.affinity import translate

logger = logging.getLogger(__name__)


@dataclass
class CorePlan:
    """단일 매스의 코어 배치 결과."""
    typology: str
    core_polygon_utm: Polygon  # 4×4m default, UTM coordinates
    core_centroid: tuple[float, float]
    distance_to_footprint_centroid: float
    inside_footprint: bool        # core가 footprint 안에 완전히 포함?
    distance_to_boundary: float   # footprint boundary 까지 최소 거리
    typology_strategy: str        # 'centroid' / 'wing_intersection' / 'inset_corner' / ...
    notes: list[str] = field(default_factory=list)


# Typology별 배치 전략
TYPOLOGY_STRATEGY = {
    "additive": "centroid",
    "subtractive": "centroid",
    "grid": "centroid",
    "tower_podium": "tower_centroid",  # upper part centroid
    "lshape": "wing_intersection",
    "cross": "wing_intersection",      # cross center
    "ushape": "inset_one_wing",
    "courtyard": "inset_one_wing",     # avoid courtyard center
    "radial": "centroid",              # radial center
    "hshape": "bridge_center",         # H 가운데 가로 부분
}


def plan_core(
    footprint_utm: Polygon,
    typology: str = "additive",
    core_size_m: float = 4.0,
) -> CorePlan:
    """
    매스 footprint + typology → 코어 위치 계산.

    Args:
        footprint_utm: UTM 좌표계 magna polygon
        typology: 매스 형태 (10종 중 1)
        core_size_m: 코어 한 변 길이 (default 4m, 4×4=16m²)

    Returns:
        CorePlan dataclass
    """
    if footprint_utm is None or footprint_utm.is_empty:
        empty = Polygon()
        return CorePlan(
            typology=typology,
            core_polygon_utm=empty,
            core_centroid=(0.0, 0.0),
            distance_to_footprint_centroid=0.0,
            inside_footprint=False,
            distance_to_boundary=0.0,
            typology_strategy="empty",
            notes=["footprint_empty"],
        )

    fp_centroid = footprint_utm.centroid
    cx, cy = fp_centroid.x, fp_centroid.y
    strategy = TYPOLOGY_STRATEGY.get(typology, "centroid")
    notes = []
    half = core_size_m / 2.0

    # 1. 후보 위치 결정
    if strategy == "centroid":
        target_x, target_y = cx, cy

    elif strategy == "wing_intersection":
        # L/Cross — 두 wing 의 교차점은 보통 footprint centroid 와 일치
        target_x, target_y = cx, cy

    elif strategy == "tower_centroid":
        # Tower part = footprint 의 *상단* (y_max 쪽 절반의 centroid)
        minx, miny, maxx, maxy = footprint_utm.bounds
        upper_box = shapely_box(minx, (miny + maxy) / 2, maxx, maxy)
        upper_part = footprint_utm.intersection(upper_box)
        if upper_part.is_empty:
            target_x, target_y = cx, cy
        else:
            target_x, target_y = upper_part.centroid.x, upper_part.centroid.y

    elif strategy == "inset_one_wing":
        # U/Courtyard — centroid 가 마당 (footprint 외부) 일 수 있음
        # → footprint 안쪽으로 inset
        if footprint_utm.contains(fp_centroid):
            # 일반 centroid 사용 가능
            target_x, target_y = cx, cy
        else:
            # representative_point: 항상 footprint 내부
            rp = footprint_utm.representative_point()
            target_x, target_y = rp.x, rp.y
            notes.append("centroid_outside_footprint_use_representative_point")

    elif strategy == "bridge_center":
        # H — 가운데 가로 bridge. 보통 footprint centroid 와 가까움
        target_x, target_y = cx, cy

    else:
        target_x, target_y = cx, cy
        notes.append(f"unknown_strategy_{strategy}_fallback_centroid")

    # 2. 코어 polygon 생성 (target 주변 core_size_m × core_size_m)
    actual_size = core_size_m
    core = shapely_box(target_x - half, target_y - half, target_x + half, target_y + half)

    # 3. footprint 안에 완전 포함되는지 확인. 아니면:
    #   (a) representative_point 로 위치 변경
    #   (b) 그래도 안 되면 코어 크기 축소 (4→3→2→1.5m)
    if not footprint_utm.contains(core):
        rp = footprint_utm.representative_point()
        target_x, target_y = rp.x, rp.y
        core = shapely_box(target_x - half, target_y - half, target_x + half, target_y + half)
        notes.append("centroid_used_representative_point")

    # 코어 축소 시도 (4m default → 3m → 2m → 1.5m)
    # Code review fix (2026-05-06): 기존 break 이 shrink 적용 *전*에 위치 → 1.5m 시도 안 됨
    for shrink in [0.75, 0.5, 0.375]:
        if footprint_utm.contains(core):
            break
        actual_size = core_size_m * shrink
        h2 = actual_size / 2.0
        core = shapely_box(target_x - h2, target_y - h2, target_x + h2, target_y + h2)
        notes.append(f"core_shrunk_to_{actual_size}m")
    # 최종 contains check (마지막 shrink 후)
    if not footprint_utm.contains(core):
        notes.append("core_shrink_exhausted")

    if not footprint_utm.contains(core):
        notes.append("core_partially_outside_footprint")

    # 4. boundary 까지 거리 (안전 마진)
    if footprint_utm.contains(core):
        dist_boundary = core.distance(footprint_utm.boundary)
    else:
        dist_boundary = 0.0

    return CorePlan(
        typology=typology,
        core_polygon_utm=core,
        core_centroid=(round(target_x, 3), round(target_y, 3)),
        distance_to_footprint_centroid=round(math.hypot(target_x - cx, target_y - cy), 3),
        inside_footprint=footprint_utm.contains(core),
        distance_to_boundary=round(dist_boundary, 3),
        typology_strategy=strategy,
        notes=notes,
    )


def core_to_geojson(plan: CorePlan, utm_to_wgs84_fn) -> dict:
    """CorePlan → GeoJSON Feature (frontend 시각화용)."""
    from shapely.geometry import mapping
    if plan.core_polygon_utm.is_empty:
        return {"type": "Feature", "geometry": None, "properties": {"kind": "core_empty"}}

    core_wgs = utm_to_wgs84_fn(plan.core_polygon_utm)
    return {
        "type": "Feature",
        "geometry": mapping(core_wgs),
        "properties": {
            "kind": "service_core",
            "typology": plan.typology,
            "strategy": plan.typology_strategy,
            "inside_footprint": plan.inside_footprint,
            "distance_to_boundary_m": plan.distance_to_boundary,
            "label": f"코어 ({plan.typology}, {plan.typology_strategy})",
            "color": "#FF6B6B",
            "fill_opacity": 0.6,
        },
    }


__all__ = [
    "CorePlan",
    "TYPOLOGY_STRATEGY",
    "plan_core",
    "core_to_geojson",
]
