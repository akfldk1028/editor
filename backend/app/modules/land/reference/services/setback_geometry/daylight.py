"""채광사선 참고 3D 경사면 and 채광 인동간격 of setback_geometry (split out of
setback_geometry.py)."""

import logging
import math

from shapely.geometry import LineString, MultiPolygon, Point, Polygon, shape
from shapely.ops import unary_union

from backend.app.modules.land.reference.services.setback_geometry.edges import _inward_normal, _utm_to_wgs, _wgs_to_utm

# Same logger name as before the split, so log routing does not change.
logger = logging.getLogger("backend.app.modules.land.reference.services.setback_geometry")


# ---------------------------------------------------------------------------
# 3b. 채광사선 참고 3D 경사면 (건축법 §61②, 시행령 §86③)
# ---------------------------------------------------------------------------

def _compute_daylight_diagonal_envelope(
    adjacent_edges: list[LineString],
    parcel_utm: Polygon,
    multiplier: float,
) -> dict | None:
    """
    채광사선제한 참고 3D 경사면 생성.

    건축법 §61②, 시행령 §86③:
    - 공동주택 채광창이 있는 벽면 → 인접대지경계선 수평거리 × multiplier 이하
    - 일반: multiplier=2, 근린상업/준주거: multiplier=4

    이 함수는 매스/채광창 벽면이 아직 없을 때의 검토 참고면만 만든다.
    실제 판정은 건축물 각 부분과 채광창 벽면의 직각방향 거리로 해야 한다.

    인접경계선 후보 전체에서 안쪽으로 경사면:
    - 경계선: H = 0
    - 안쪽 d미터: H = d × multiplier

    구간별 별도 polygon. 각 면은 대지 polygon으로 clip하여 밖으로 나가지
    않고, 꼭짓점 높이는 해당 경계선과의 수평거리로 계산한다.

    Returns: {"walls": [...], "multiplier": float} or None
    """
    try:
        if not adjacent_edges:
            return None

        centroid = parcel_utm.centroid
        # 필지 크기 기반 max_depth (밖으로 돌출 방지)
        bounds = parcel_utm.bounds  # (minx, miny, maxx, maxy)
        parcel_span = min(bounds[2] - bounds[0], bounds[3] - bounds[1])
        # 시각화 보수적: 필지 최소 차원 40% 또는 12m cap (이전 30m는 너무 큼)
        max_depth = min(parcel_span * 0.4, 12.0)
        if max_depth < 3.0:
            return None
        walls = []
        strips = []

        for edge_idx, edge in enumerate(adjacent_edges):
            nx, ny = _inward_normal(edge, centroid)
            if nx != 0.0 or ny != 0.0:
                edge_coords = list(edge.coords)
                if len(edge_coords) < 2:
                    continue
                p1, p2 = edge_coords[0], edge_coords[-1]
                strip = Polygon([
                    p1,
                    p2,
                    (p2[0] + nx * max_depth, p2[1] + ny * max_depth),
                    (p1[0] + nx * max_depth, p1[1] + ny * max_depth),
                ])
                clipped = strip.intersection(parcel_utm)
                if not clipped.is_empty:
                    strips.append(clipped)
                if clipped.is_empty:
                    continue
                if isinstance(clipped, MultiPolygon):
                    polygons = [g for g in clipped.geoms if g.area > 0.1]
                elif isinstance(clipped, Polygon):
                    polygons = [clipped] if clipped.area > 0.1 else []
                else:
                    polygons = []

                for poly_idx, poly in enumerate(polygons):
                    coords = list(poly.exterior.coords)[:-1]
                    if len(coords) < 3:
                        continue
                    positions_wgs = []
                    min_h = []
                    max_h = []
                    for pt in coords:
                        wgs_pt = _utm_to_wgs(Point(pt[0], pt[1]))
                        positions_wgs.append([wgs_pt.x, wgs_pt.y])
                        dist_m = min(max(edge.distance(Point(pt[0], pt[1])), 0.0), max_depth)
                        min_h.append(0.0)
                        max_h.append(dist_m * multiplier)
                    walls.append({
                        "positions": positions_wgs,
                        "min_heights": min_h,
                        "max_heights": max_h,
                        "edge_index": edge_idx,
                        "polygon_index": poly_idx,
                    })

        if not walls:
            return None

        surface_domain = unary_union(strips).intersection(parcel_utm) if strips else None
        surface_polygons = _daylight_reference_surface_shells(
            surface_domain, adjacent_edges, multiplier, max_depth,
        )
        reference_edges = _daylight_reference_edges(adjacent_edges)

        return {
            "walls": walls,
            "surface_polygons": surface_polygons,
            "reference_edges": reference_edges,
            "multiplier": multiplier,
            "max_depth_m": max_depth,
            "reference_only": True,
            "law_basis": "건축법 §61②, 건축법 시행령 §86③",
            "target_reference": "공동주택 채광창이 있는 벽면에서 직각방향 인접대지경계선까지의 수평거리",
        }

    except Exception as e:
        logger.warning(f"daylight_diagonal_envelope failed: {e}")
        return None


def _daylight_reference_surface_shells(
    domain,
    adjacent_edges: list[LineString],
    multiplier: float,
    max_depth: float,
) -> list[dict]:
    """겹치는 strip들을 큰 외곽 surface 단위로 변환.

    삼각 mesh를 여러 entity로 그리면 반투명 경계가 내부 대각선처럼 보인다.
    기본 검토 화면은 정북일조처럼 하나의 얇은 면으로 읽혀야 하므로 union된
    domain의 exterior shell만 보낸다. 정밀 샘플/디버그는 기존 walls를 사용한다.
    """
    if domain is None or domain.is_empty:
        return []

    geoms = list(domain.geoms) if isinstance(domain, MultiPolygon) else [domain]
    surface_polygons: list[dict] = []
    for poly in geoms:
        if not isinstance(poly, Polygon) or poly.area < 0.1:
            continue
        coords = _densify_ring(list(poly.exterior.coords)[:-1], max(1.5, min(max_depth / 3.0, 3.0)))
        if len(coords) < 3:
            continue
        positions_wgs = []
        heights = []
        for pt in coords:
            point = Point(pt[0], pt[1])
            dist_m = min(
                max(min(edge.distance(point) for edge in adjacent_edges), 0.0),
                max_depth,
            )
            wgs_pt = _utm_to_wgs(point)
            positions_wgs.append([wgs_pt.x, wgs_pt.y])
            heights.append(dist_m * multiplier)
        surface_polygons.append({
            "positions": positions_wgs,
            "max_heights": heights,
        })
    return surface_polygons


def _densify_ring(coords: list[tuple], max_segment_m: float) -> list[tuple[float, float]]:
    dense: list[tuple[float, float]] = []
    if not coords:
        return dense
    ring = coords + [coords[0]]
    for a, b in zip(ring, ring[1:]):
        ax, ay = float(a[0]), float(a[1])
        bx, by = float(b[0]), float(b[1])
        length = math.hypot(bx - ax, by - ay)
        steps = max(1, int(math.ceil(length / max_segment_m)))
        for i in range(steps):
            t = i / steps
            pt = (ax + (bx - ax) * t, ay + (by - ay) * t)
            if not dense or dense[-1] != pt:
                dense.append(pt)
    return dense


def _daylight_reference_edges(adjacent_edges: list[LineString]) -> list[dict]:
    edges = []
    for edge in adjacent_edges:
        positions = []
        for pt in edge.coords:
            wgs_pt = _utm_to_wgs(Point(pt[0], pt[1]))
            positions.append([wgs_pt.x, wgs_pt.y])
        if len(positions) >= 2:
            edges.append({"positions": positions, "height_m": 0.0})
    return edges


# ---------------------------------------------------------------------------
# 5. 채광 인동간격 (§61②, 령§86③) — 매스 쌍 입력시
# ---------------------------------------------------------------------------

def compute_daylight_distance(
    building_a: dict,
    building_b: dict,
    is_urban_living: bool = False,
    footprint_a: dict | None = None,
    footprint_b: dict | None = None,
) -> dict:
    """
    두 건물 매스 간 채광 인동간격 검증.

    건축법 §61②, 시행령 §86③:
    - 같은 대지 내 공동주택 동 간: H × 0.5 이상 (일반)
    - 도시형 생활주택: H × 0.25 이상
    - 인접대지경계선 방향: 채광창~경계선 수평거리 × 2 이하 높이

    Args:
        building_a: {"height": float, "centroid": [x, y] (WGS84)}
        building_b: {"height": float, "centroid": [x, y] (WGS84)}
        is_urban_living: 도시형 생활주택 ���부

    Returns:
        {
            "distance_m": float,     # 두 동 간 실제 거리
            "required_m": float,     # 최소 이격거리
            "ratio": float,          # 이격비 (H 대비)
            "compliant": bool,       # 기준 충족 여부
            "taller_height_m": float,
            "formula": str,
        }
    """
    h_a = building_a.get("height", 0)
    h_b = building_b.get("height", 0)
    taller = max(h_a, h_b)

    multiplier = 0.25 if is_urban_living else 0.5
    required = taller * multiplier

    # 두 동 간 거리 (UTM 변환)
    # footprint(GeoJSON) 있으면 면 대 면 최단거리, 없으면 centroid 간 거리
    try:
        if footprint_a and footprint_b:
            fp_a_utm = _wgs_to_utm(shape(footprint_a))
            fp_b_utm = _wgs_to_utm(shape(footprint_b))
            distance = fp_a_utm.distance(fp_b_utm)
        else:
            pt_a = _wgs_to_utm(Point(building_a["centroid"][0], building_a["centroid"][1]))
            pt_b = _wgs_to_utm(Point(building_b["centroid"][0], building_b["centroid"][1]))
            distance = pt_a.distance(pt_b)
    except Exception:
        distance = 0.0

    return {
        "distance_m": round(distance, 2),
        "required_m": round(required, 2),
        "ratio": round(distance / taller, 3) if taller > 0 else 0,
        "compliant": distance >= required,
        "taller_height_m": taller,
        "formula": f"H×{multiplier} = {taller}×{multiplier} = {required:.1f}m",
    }
