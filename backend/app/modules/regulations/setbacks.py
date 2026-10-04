"""
Setback Geometry — 필지 polygon + 규제 수치 → 규제선 GeoJSON 생성.

건축법 규제선 7종 중 6종 생성:
1. buildable_area: 건축가능영역 (인접이격 buffer)
2. north_setback: 정북 일조사선 (§61①, 령§86①)
3. adjacent_setback: 인접대지 이격선 (§58, 령§80조의2)
4. road_setback: 건축선 후퇴 (§46-47) — 최장변=도로 휴리스틱
5. corner_cutoff: 가각전제 (령§31) — 도로변 교차 삼각 클립
6. daylight_distance: 채광 인동간격 (§61②, 령§86③) — 매스 쌍 입력시

7. building_designation_line: 건축지정선/한계선 (지구단위계획 §49-52) — 도로변 기준 기본값
pyproj Transformer는 design/services/site_geometry.py와 동일 CRS지만
land↔design 의존성을 피하기 위해 독립 인스턴스 사용.
"""

import logging
import math

from shapely.geometry import LineString, MultiLineString, MultiPolygon, Point, Polygon, mapping, shape
from shapely.ops import transform, unary_union
from pyproj import Transformer

from .sunlight_envelope import compute_sunlight_envelope

logger = logging.getLogger(__name__)

# Korea UTM zone 52N
_to_utm = Transformer.from_crs("EPSG:4326", "EPSG:32652", always_xy=True)
_to_wgs = Transformer.from_crs("EPSG:32652", "EPSG:4326", always_xy=True)


def _wgs_to_utm(geom):
    return transform(_to_utm.transform, geom)


def _utm_to_wgs(geom):
    return transform(_to_wgs.transform, geom)


def compute_setback_lines(
    parcel_geojson: dict,
    regulations: dict,
    *,
    compute_datum: bool = False,
    road_frontages: list[dict] | None = None,
    neighbor_parcels: list[dict] | None = None,
) -> dict:
    """
    필지 polygon + 규제 수치 → 규제선 GeoJSON dict.

    Args:
        parcel_geojson: GeoJSON geometry (Polygon from Vworld)
        regulations: regulation_calculator.calculate_all() 결과
        compute_datum: True raises NotImplementedError until the elevation
            provider is migrated. False preserves relative envelope heights
            with elevation_source=None.
        road_frontages: Vworld 인접 도로 필지에서 추출한 공유변/도로폭 정보.
            있으면 최장변 휴리스틱 대신 실제 도로 접면 기준으로 road edge를 분류.

    Returns:
        {
            "buildable_area": GeoJSON polygon | None,
            "north_setback": GeoJSON LineString/MultiLineString | None,
            "adjacent_setback": GeoJSON LineString/MultiLineString | None,
            "road_setback": GeoJSON LineString/MultiLineString | None,
            ...
            "datum_result": None,
        }
    """
    if compute_datum:
        raise NotImplementedError("datum elevation has not been migrated")
    result = {
        "buildable_area": None,
        "north_setback": None,
        "adjacent_setback": None,
        "road_setback": None,
        "corner_cutoff": None,                # 가각전제 삼각 클립
        "sunlight_envelope": None,            # 3D 일조사선 (walls + slanted_polygons, envelopes/sunlight.py)
        "building_designation_line": None,    # 건축지정선/한계선 (지구단위계획)
        "daylight_diagonal_envelope": None,   # 채광사선제한 3D (§86③, 공동주택)
        "datum_result": None,
    }

    # Validate geometry input
    if not isinstance(parcel_geojson, dict):
        return result
    if "type" not in parcel_geojson or "coordinates" not in parcel_geojson:
        return result

    try:
        parcel = shape(parcel_geojson)
        if not parcel.is_valid or parcel.is_empty:
            return result
        # MultiPolygon → 최대 면적 Polygon 추출
        if isinstance(parcel, MultiPolygon):
            parcel = max(parcel.geoms, key=lambda g: g.area)
        if not isinstance(parcel, Polygon):
            return result
        parcel_utm = _wgs_to_utm(parcel)
    except Exception as e:
        logger.warning(f"setback_geometry: parcel parse failed: {e}")
        return result

    adjacent_m = regulations.get("adjacent_setback_m") or 0.5
    road_setback_m = regulations.get("building_line_setback_m") or 1.0
    sunlight_applies = regulations.get("sunlight_applies", False)
    sunlight_rules = regulations.get("sunlight_rules", [])
    corner_cutoff_required = regulations.get("corner_cutoff_required", False)

    # Step 1: 건축가능영역 (일괄 buffer)
    result["buildable_area"] = _compute_buildable_area(parcel_utm, adjacent_m)

    # Step 2: 변별 규제선
    edges = _extract_edges(parcel_utm)
    if not edges:
        return result

    classified = _classify_edges(edges, parcel_utm, road_frontages=road_frontages)

    # 정북 일조사선 (2D multi-height lines + 3D envelope)
    if sunlight_applies and classified["north"]:
        result["north_setback"] = _compute_sunlight_setback_lines(
            classified["north"], parcel_utm, sunlight_rules,
        )
        result["sunlight_envelope"] = compute_sunlight_envelope(
            classified["north"], parcel_utm, sunlight_rules,
            datum=None,
        )

    # 인접대지 이격선
    if classified["adjacent"] and adjacent_m > 0:
        result["adjacent_setback"] = _offset_edges_inward(
            classified["adjacent"], parcel_utm, adjacent_m,
        )

    # 도로변 건축선 후퇴 (§46-47)
    if classified["road"]:
        road_lines = []
        for idx, edge in enumerate(classified["road"]):
            width = classified.get("road_widths", [])[idx] if idx < len(classified.get("road_widths", [])) else 0
            setback_m = _road_setback_by_width(width) if width > 0 else road_setback_m
            if setback_m > 0:
                road_lines.append((edge, setback_m))
        if road_lines:
            result["road_setback"] = _offset_edges_with_distances_inward(road_lines, parcel_utm)

    # 가각전제 (령§31): 도로변 교차 꼭짓점에서 삼각 클립
    # cutoff_m: 조례/zone override 또는 도로폭 기반 동적 계산
    corner_cutoff_m = regulations.get("corner_cutoff_m")  # None = 동적 계산
    if corner_cutoff_required and classified["road"]:
        result["corner_cutoff"] = _compute_corner_cutoff(
            classified["road"], parcel_utm, cutoff_m=corner_cutoff_m,
        )

    # 건축지정선/한계선 (국토계획법 §49-52): 지구단위계획구역 도로변 기준
    designation_applies = regulations.get("building_designation_applies", False)
    designation_setback = regulations.get("building_designation_setback_m")
    if designation_applies and classified["road"] and designation_setback and designation_setback > 0:
        result["building_designation_line"] = _offset_edges_inward(
            classified["road"], parcel_utm, designation_setback,
        )

    # 채광사선제한 3D 경사면 (시행령 §86③): 공동주택, 인접경계선에서 H ≤ 거리 × mult
    daylight_mult = regulations.get("daylight_diagonal_multiplier")
    if daylight_mult and classified["adjacent"]:
        result["daylight_diagonal_envelope"] = _compute_daylight_diagonal_envelope(
            classified["adjacent"], parcel_utm, daylight_mult,
        )

    return result


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

