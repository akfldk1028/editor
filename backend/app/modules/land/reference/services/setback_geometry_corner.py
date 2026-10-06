"""가각전제 of `setback_geometry.compute_setback_lines` (split out of setback_geometry.py)."""

import logging
import math

from shapely.geometry import LineString, Polygon, mapping

from backend.app.modules.land.reference.services.setback_geometry_edges import _utm_to_wgs

# Same logger name as before the split, so log routing does not change.
logger = logging.getLogger(__name__.rpartition(".")[0] + ".setback_geometry")


# ---------------------------------------------------------------------------
# 4. 가각전제 (령§31) — 도로변 교차 꼭짓점 삼각 클립
# ---------------------------------------------------------------------------

def _compute_corner_cutoff(
    road_edges: list[LineString],
    parcel_utm: Polygon,
    cutoff_m: float | None = None,
) -> dict | None:
    """
    가각전제: 두 도로변이 만나는 꼭짓점에서 삼각형 잘라내기.

    건축법 시행령 §31: 너비 8m 미만 도로 교차부.
    도로폭/교차각에 따라 절삭 거리 차등 적용:
      교차각 < 90°: 6~8m도로=4m, 4~6m도로=3m
      90~120°: 6~8m도로=3m, 4~6m도로=2m
      ≥ 120°: 적용 안 함

    Args:
        road_edges: 도로변으로 분류된 LineString 리스트
        parcel_utm: UTM 투영 필지 Polygon
        cutoff_m: 조례 override 절삭 길이. None이면 교차각 기반 동적 계산.

    Returns:
        GeoJSON Polygon (잘린 삼각형 영역) or None
    """
    if len(road_edges) < 2:
        return None

    try:
        # 도로변들의 끝점 공유 → 교차 꼭짓점 찾기
        corners = []
        for i in range(len(road_edges)):
            for j in range(i + 1, len(road_edges)):
                shared = _find_shared_vertex(road_edges[i], road_edges[j])
                if shared:
                    corners.append((shared, road_edges[i], road_edges[j]))

        if not corners:
            return None

        triangles = []
        for corner_pt, edge_a, edge_b in corners:
            # 교차각 기반 절삭 거리 계산 (조례 override 없을 때)
            actual_cutoff = cutoff_m if cutoff_m is not None else _corner_cutoff_by_angle(edge_a, edge_b, corner_pt)
            if actual_cutoff <= 0:
                continue
            pt_a = _point_along_edge_from(edge_a, corner_pt, actual_cutoff)
            pt_b = _point_along_edge_from(edge_b, corner_pt, actual_cutoff)
            if pt_a and pt_b:
                tri = Polygon([corner_pt, pt_a, pt_b, corner_pt])
                if tri.is_valid and tri.area > 0.01:
                    triangles.append(tri)

        if not triangles:
            return None

        # 삼각형들을 합쳐서 반환
        from shapely.ops import unary_union
        merged = unary_union(triangles)
        merged_wgs = _utm_to_wgs(merged)
        return mapping(merged_wgs)

    except Exception as e:
        logger.warning(f"corner_cutoff failed: {e}")
        return None


def _corner_cutoff_by_angle(
    edge_a: LineString, edge_b: LineString, shared_vertex: tuple | None = None,
) -> float:
    """
    시행령 §31 교차각 기반 가각전제 절삭 거리 (m).

    | 교차각   | 절삭 거리 |
    |---------|----------|
    | < 90°   | 3m       |
    | 90~120° | 2m       |
    | ≥ 120°  | 0 (없음)  |
    """
    # Orient vectors AWAY from shared vertex for correct angle
    if shared_vertex:
        sx, sy = shared_vertex
        # Pick the endpoint of each edge that is NOT the shared vertex
        d0a = (edge_a.coords[0][0] - sx) ** 2 + (edge_a.coords[0][1] - sy) ** 2
        d1a = (edge_a.coords[1][0] - sx) ** 2 + (edge_a.coords[1][1] - sy) ** 2
        if d0a < d1a:
            dx_a = edge_a.coords[1][0] - sx
            dy_a = edge_a.coords[1][1] - sy
        else:
            dx_a = edge_a.coords[0][0] - sx
            dy_a = edge_a.coords[0][1] - sy

        d0b = (edge_b.coords[0][0] - sx) ** 2 + (edge_b.coords[0][1] - sy) ** 2
        d1b = (edge_b.coords[1][0] - sx) ** 2 + (edge_b.coords[1][1] - sy) ** 2
        if d0b < d1b:
            dx_b = edge_b.coords[1][0] - sx
            dy_b = edge_b.coords[1][1] - sy
        else:
            dx_b = edge_b.coords[0][0] - sx
            dy_b = edge_b.coords[0][1] - sy
    else:
        dx_a = edge_a.coords[1][0] - edge_a.coords[0][0]
        dy_a = edge_a.coords[1][1] - edge_a.coords[0][1]
        dx_b = edge_b.coords[1][0] - edge_b.coords[0][0]
        dy_b = edge_b.coords[1][1] - edge_b.coords[0][1]

    len_a = math.sqrt(dx_a * dx_a + dy_a * dy_a)
    len_b = math.sqrt(dx_b * dx_b + dy_b * dy_b)
    if len_a < 0.01 or len_b < 0.01:
        return 3.0

    # Interior angle between vectors pointing away from shared vertex
    cos_angle = (dx_a * dx_b + dy_a * dy_b) / (len_a * len_b)
    cos_angle = min(1.0, max(-1.0, cos_angle))
    angle_deg = math.degrees(math.acos(cos_angle))

    if angle_deg >= 120:
        return 0.0  # 120° 이상: 가각전제 불필요
    elif angle_deg >= 90:
        return 2.0  # 90~120°: 보수적 2m
    else:
        return 3.0  # 90° 미만: 보수적 3m


def _find_shared_vertex(
    edge_a: LineString, edge_b: LineString, tolerance: float = 0.5,
) -> tuple | None:
    """두 LineString이 공유하는 꼭짓점 찾기 (tolerance 이내)."""
    for pa in edge_a.coords:
        for pb in edge_b.coords:
            dist = math.sqrt((pa[0] - pb[0]) ** 2 + (pa[1] - pb[1]) ** 2)
            if dist < tolerance:
                return ((pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2)
    return None


def _point_along_edge_from(
    edge: LineString, start_pt: tuple, distance: float,
) -> tuple | None:
    """edge 위에서 start_pt로부터 distance(m)만큼 떨어진 점 반환."""
    coords = list(edge.coords)
    # start_pt에 가까운 쪽이 시작점
    d0 = math.sqrt((coords[0][0] - start_pt[0]) ** 2 + (coords[0][1] - start_pt[1]) ** 2)
    d1 = math.sqrt((coords[-1][0] - start_pt[0]) ** 2 + (coords[-1][1] - start_pt[1]) ** 2)
    if d1 < d0:
        coords = list(reversed(coords))

    # 시작점에서 distance만큼 이동
    remaining = distance
    for i in range(len(coords) - 1):
        seg_len = math.sqrt(
            (coords[i + 1][0] - coords[i][0]) ** 2 +
            (coords[i + 1][1] - coords[i][1]) ** 2,
        )
        if seg_len < 0.001:
            continue
        if remaining <= seg_len:
            ratio = remaining / seg_len
            return (
                coords[i][0] + ratio * (coords[i + 1][0] - coords[i][0]),
                coords[i][1] + ratio * (coords[i + 1][1] - coords[i][1]),
            )
        remaining -= seg_len

    return None
