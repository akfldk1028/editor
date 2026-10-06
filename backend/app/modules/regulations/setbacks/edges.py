"""Edge classification and inward offsets of `setbacks.compute_setback_lines`
(split out of setbacks.py). Holds the WGS84 <-> UTM 52N transformers.
"""

import logging
import math

from shapely.geometry import LineString, MultiLineString, MultiPolygon, Point, Polygon, mapping
from shapely.ops import transform
from pyproj import Transformer

# Same logger name as before the split, so log routing does not change.
logger = logging.getLogger("backend.app.modules.regulations.setbacks")


# Korea UTM zone 52N
_to_utm = Transformer.from_crs("EPSG:4326", "EPSG:32652", always_xy=True)
_to_wgs = Transformer.from_crs("EPSG:32652", "EPSG:4326", always_xy=True)


def _wgs_to_utm(geom):
    return transform(_to_utm.transform, geom)


def _utm_to_wgs(geom):
    return transform(_to_wgs.transform, geom)


def _compute_buildable_area(parcel_utm: Polygon, setback_m: float) -> dict | None:
    """필지 → buffer(-setback) → 건축가능영역 GeoJSON."""
    try:
        buildable = parcel_utm.buffer(-setback_m)
        if buildable.is_empty or buildable.area < 1.0:
            return None
        # buffer can produce MultiPolygon on concave shapes → take largest
        if isinstance(buildable, MultiPolygon):
            buildable = max(buildable.geoms, key=lambda g: g.area)
        buildable_wgs = _utm_to_wgs(buildable)
        return mapping(buildable_wgs)
    except Exception as e:
        logger.warning(f"buildable_area failed: {e}")
        return None


def _extract_edges(polygon_utm: Polygon) -> list[tuple]:
    """Polygon 외곽선 → [(LineString, azimuth)] 리스트."""
    coords = list(polygon_utm.exterior.coords)
    edges = []
    for i in range(len(coords) - 1):
        p1 = coords[i]
        p2 = coords[i + 1]
        line = LineString([p1, p2])
        if line.length < 0.1:
            continue
        az = _azimuth(p1, p2)
        edges.append((line, az))
    return edges


def _inward_normal(edge: LineString, centroid: Point) -> tuple[float, float]:
    """Compute unit inward-pointing normal of an edge relative to polygon centroid."""
    dx = edge.coords[1][0] - edge.coords[0][0]
    dy = edge.coords[1][1] - edge.coords[0][1]
    length = math.sqrt(dx * dx + dy * dy)
    if length < 0.01:
        return (0.0, 0.0)
    # Left-turn normal
    nx = -dy / length
    ny = dx / length
    # Flip to point inward (toward centroid)
    mid = edge.interpolate(0.5, normalized=True)
    to_cx = centroid.x - mid.x
    to_cy = centroid.y - mid.y
    if nx * to_cx + ny * to_cy < 0:
        nx, ny = -nx, -ny
    return (nx, ny)


def _azimuth(p1: tuple, p2: tuple) -> float:
    """두 점 사이 방위각 (0=북, 90=동, 180=남, 270=서). UTM 좌표 기준."""
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    az = math.degrees(math.atan2(dx, dy)) % 360
    return az


def _classify_edges(edges: list[tuple], parcel_utm: Polygon,
                    road_frontages: list[dict] | None = None) -> dict:
    """
    변의 바깥쪽 법선 방향으로 분류:
    - north: 바깥 법선이 정북(y+) 방향인 변 → 일조사선 적용
      법선 방위각 300°~60° (정북 ±60°)
      건축법 §61①: "정북(正北) 방향으로의 인접 대지경계선"
      NOTE: UTM Zone 52N의 Grid North ≈ True North (한국 중부 자오선 수렴각 <0.5°)
    - road: 최장변 1개 (한국 필지 관행: 전면도로 = 가장 긴 변).
      코너 필지면 최장변과 꼭지점을 공유하는 인접 변 중 최장변 70% 이상 길이의 변도 도로변.
      **최대 2개로 제한** (정사각형 필지가 전부 road 되는 버그 방지).
    - adjacent: 나머지 (인접대지) — 항상 최소 1개 이상 보존.
    """
    classified = {"north": [], "road": [], "adjacent": [], "road_widths": []}

    if not edges:
        return classified

    centroid = parcel_utm.centroid

    # ── 1단계: 모든 변에 대해 북향 판정 + 바깥 법선 계산
    edge_meta = []
    for line, az in edges:
        dx = line.coords[1][0] - line.coords[0][0]
        dy = line.coords[1][1] - line.coords[0][1]
        length = math.sqrt(dx * dx + dy * dy)
        if length < 0.01:
            continue

        nx = -dy / length
        ny = dx / length
        mid = line.interpolate(0.5, normalized=True)
        to_center_x = centroid.x - mid.x
        to_center_y = centroid.y - mid.y
        if nx * to_center_x + ny * to_center_y > 0:
            nx, ny = -nx, -ny
        normal_az = math.degrees(math.atan2(nx, ny)) % 360
        is_north_facing = normal_az >= 300 or normal_az <= 60
        edge_meta.append((line, line.length, is_north_facing))

    if not edge_meta:
        return classified

    matched_roads = _match_edges_to_road_frontages(edge_meta, road_frontages)

    # ── 2단계: 도로변 선정
    # 실제 Vworld 인접 도로 필지 공유변이 있으면 그 결과를 우선 사용.
    if any(is_road for is_road, _ in matched_roads):
        for (line, _, is_north_facing), (is_road, width_m) in zip(edge_meta, matched_roads):
            if is_road:
                classified["road"].append(line)
                classified["road_widths"].append(width_m)
                if is_north_facing:
                    classified["north"].append(line)
            elif is_north_facing:
                classified["north"].append(line)
            else:
                classified["adjacent"].append(line)
        return classified

    # Vworld 도로 접면이 없을 때만 최장변 휴리스틱 사용.
    edge_meta.sort(key=lambda m: -m[1])  # 긴 순
    longest_line = edge_meta[0][0]
    max_length = edge_meta[0][1]
    road_threshold = max_length * 0.70
    road_lines = [longest_line]

    # 두번째 도로 후보: 최장변과 꼭지점 공유 + 길이 ≥ 70%
    for m in edge_meta[1:]:
        cand, length, _ = m
        if length < road_threshold:
            break
        # 꼭지점 공유 체크
        ep_long = {longest_line.coords[0], longest_line.coords[1]}
        ep_cand = {cand.coords[0], cand.coords[1]}
        if ep_long & ep_cand:
            road_lines.append(cand)
            break  # 최대 2개

    # ── 3단계: 분류 (road 우선, 나머지는 북향 or 인접)
    road_set = {id(l) for l in road_lines}
    for line, _, is_north_facing in edge_meta:
        if id(line) in road_set:
            classified["road"].append(line)
            classified["road_widths"].append(0.0)
            if is_north_facing:
                classified["north"].append(line)
        elif is_north_facing:
            classified["north"].append(line)
        else:
            classified["adjacent"].append(line)

    # ── 방어: adjacent가 하나도 없으면 (극히 작은 필지) 도로 아닌 모든 변 복귀
    if not classified["adjacent"] and len(edge_meta) > len(road_lines):
        for line, _, _ in edge_meta:
            if id(line) not in road_set and line not in classified["north"]:
                classified["adjacent"].append(line)

    return classified


def _match_edges_to_road_frontages(
    edge_meta: list[tuple], road_frontages: list[dict] | None,
) -> list[tuple[bool, float]]:
    if not road_frontages:
        return [(False, 0.0) for _ in edge_meta]

    road_lines = []
    for frontage in road_frontages:
        shared = frontage.get("sharedEdge") or frontage.get("shared_edge")
        if not shared or len(shared) < 2:
            continue
        try:
            line = LineString([_to_utm.transform(float(x), float(y)) for x, y in shared])
            road_lines.append((line, float(frontage.get("roadWidthM") or frontage.get("road_width_m") or 0.0)))
        except (TypeError, ValueError):
            continue

    matches = []
    for line, _, _ in edge_meta:
        mid = line.interpolate(0.5, normalized=True)
        best_width = 0.0
        best_dist = 999999.0
        for road_line, width_m in road_lines:
            dist = mid.distance(road_line)
            if dist < best_dist:
                best_dist = dist
                best_width = width_m
        matches.append((best_dist < 2.0, best_width if best_dist < 2.0 else 0.0))
    return matches


def _road_setback_by_width(road_width_m: float) -> float:
    """건축법상 4m 미만 도로의 중심선 기준 확보를 시각화용 후퇴거리로 환산."""
    if road_width_m >= 4.0:
        return 0.0
    return max(0.0, (4.0 - road_width_m) / 2.0)




def _compute_sunlight_setback_lines(
    north_edges: list[LineString],
    parcel_utm: Polygon,
    sunlight_rules: list,
) -> dict | None:
    """
    정북일조 사선을 높이별로 여러 선 생성 → GeoJSON FeatureCollection.

    건축법 시행령 §86①:
    - H ≤ 10m: 1.5m 이격
    - H > 10m: H/2 이격

    여러 높이(10m, 20m, 30m, 40m)에 대해 사선 위치를 표시하면
    지도에서 사선 범위가 명확하게 보임.

    모든 선은 필지 polygon 내부로 클리핑됨.
    """
    # 높이별 (높이, 이격거리, 라벨)
    height_steps = [
        (10, 1.5, "H=10m → 1.5m"),
        (20, 10.0, "H=20m → 10m"),
        (30, 15.0, "H=30m → 15m"),
        (40, 20.0, "H=40m → 20m"),
    ]

    centroid = parcel_utm.centroid
    features = []

    for height_m, offset_m, label in height_steps:
        lines_for_height = []
        for edge in north_edges:
            nx, ny = _inward_normal(edge, centroid)
            if nx == 0.0 and ny == 0.0:
                continue
            offset_coords = [
                (c[0] + nx * offset_m, c[1] + ny * offset_m)
                for c in edge.coords
            ]
            line = LineString(offset_coords)
            # 필지 내부로 클리핑 — 밖으로 돌출 방지
            clipped = line.intersection(parcel_utm)
            if clipped.is_empty:
                continue
            if isinstance(clipped, (LineString, MultiLineString)) and clipped.length > 0.1:
                lines_for_height.append(clipped)

        if not lines_for_height:
            continue

        if len(lines_for_height) == 1:
            geom = lines_for_height[0]
        else:
            all_lines = []
            for g in lines_for_height:
                if isinstance(g, MultiLineString):
                    all_lines.extend(g.geoms)
                else:
                    all_lines.append(g)
            geom = MultiLineString(all_lines) if len(all_lines) > 1 else all_lines[0]

        geom_wgs = _utm_to_wgs(geom)
        features.append({
            "type": "Feature",
            "properties": {
                "height_m": height_m,
                "offset_m": offset_m,
                "label": label,
            },
            "geometry": mapping(geom_wgs),
        })

    if not features:
        return None

    return {
        "type": "FeatureCollection",
        "features": features,
    }


def _offset_edges_inward(
    edges: list[LineString],
    parcel_utm: Polygon,
    distance: float,
) -> dict | None:
    """
    변들을 필지 안쪽으로 offset → GeoJSON LineString/MultiLineString.

    각 변을 법선(normal) 방향으로 inward offset.
    """
    try:
        offset_lines = []
        centroid = parcel_utm.centroid

        for edge in edges:
            nx, ny = _inward_normal(edge, centroid)
            if nx == 0.0 and ny == 0.0:
                continue

            # offset 적용
            offset_coords = [
                (c[0] + nx * distance, c[1] + ny * distance)
                for c in edge.coords
            ]
            offset_line = LineString(offset_coords)
            if not offset_line.is_empty and offset_line.length > 0.1:
                offset_lines.append(offset_line)

        if not offset_lines:
            return None

        if len(offset_lines) == 1:
            result_geom = _utm_to_wgs(offset_lines[0])
        else:
            result_geom = _utm_to_wgs(MultiLineString(offset_lines))

        return mapping(result_geom)

    except Exception as e:
        logger.warning(f"offset_edges_inward failed: {e}")
        return None


def _offset_edges_with_distances_inward(
    edges_with_distances: list[tuple[LineString, float]],
    parcel_utm: Polygon,
) -> dict | None:
    """Offset road edges inward when each frontage has a different road width."""
    try:
        offset_lines = []
        centroid = parcel_utm.centroid
        for edge, distance in edges_with_distances:
            nx, ny = _inward_normal(edge, centroid)
            if nx == 0.0 and ny == 0.0:
                continue
            offset_coords = [
                (c[0] + nx * distance, c[1] + ny * distance)
                for c in edge.coords
            ]
            offset_line = LineString(offset_coords)
            if not offset_line.is_empty and offset_line.length > 0.1:
                offset_lines.append(offset_line)

        if not offset_lines:
            return None
        if len(offset_lines) == 1:
            result_geom = _utm_to_wgs(offset_lines[0])
        else:
            result_geom = _utm_to_wgs(MultiLineString(offset_lines))
        return mapping(result_geom)
    except Exception as e:
        logger.warning(f"offset_edges_with_distances_inward failed: {e}")
        return None
