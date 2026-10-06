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
from dataclasses import replace

from shapely.geometry import LineString, MultiPolygon, Polygon, shape

from backend.app.modules.land.reference.services.envelopes.sunlight import compute_sunlight_envelope
from backend.app.modules.land.reference.services.setback_geometry_edges import (
    _to_utm,
    _to_wgs,
    _wgs_to_utm,
    _utm_to_wgs,
    _compute_buildable_area,
    _extract_edges,
    _inward_normal,
    _azimuth,
    _classify_edges,
    _match_edges_to_road_frontages,
    _road_setback_by_width,
    _sunlight_offset,
    _compute_sunlight_setback_lines,
    _offset_edges_inward,
    _offset_edges_with_distances_inward,
)
from backend.app.modules.land.reference.services.setback_geometry_daylight import (
    _compute_daylight_diagonal_envelope,
    _daylight_reference_surface_shells,
    _densify_ring,
    _daylight_reference_edges,
    compute_daylight_distance,
)
from backend.app.modules.land.reference.services.setback_geometry_corner import (
    _compute_corner_cutoff,
    _corner_cutoff_by_angle,
    _find_shared_vertex,
    _point_along_edge_from,
)

logger = logging.getLogger(__name__)


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
        compute_datum: True면 §119 datum 계산 후 envelope에 주입 (Phase 2B opt-in,
            keyword-only). False (default) → envelope.elevation_source=None
            → frontend는 terrain.getHeight() fallback (LOCKED SPEC 동일).
        road_frontages: Vworld 인접 도로 필지에서 추출한 공유변/도로폭 정보.
            있으면 최장변 휴리스틱 대신 실제 도로 접면 기준으로 road edge를 분류.

    Returns:
        {
            "buildable_area": GeoJSON polygon | None,
            "north_setback": GeoJSON LineString/MultiLineString | None,
            "adjacent_setback": GeoJSON LineString/MultiLineString | None,
            "road_setback": GeoJSON LineString/MultiLineString | None,
            ...
            "datum_result": dict | None,  # Phase 2B 디버그용 (compute_datum=True)
        }
    """
    result = {
        "buildable_area": None,
        "north_setback": None,
        "adjacent_setback": None,
        "road_setback": None,
        "corner_cutoff": None,                # 가각전제 삼각 클립
        "sunlight_envelope": None,            # 3D 일조사선 (walls + slanted_polygons, envelopes/sunlight.py)
        "building_designation_line": None,    # 건축지정선/한계선 (지구단위계획)
        "daylight_diagonal_envelope": None,   # 채광사선제한 3D (§86③, 공동주택)
        "datum_result": None,                 # Phase 2B (compute_datum=True 시)
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

    # Phase 2B: datum 계산 (compute_datum=True 시)
    datum_result = _maybe_compute_datum(
        parcel, compute_datum, road_frontages, neighbor_parcels, classified["north"],
    )
    if datum_result is not None:
        result["datum_result"] = _datum_to_dict(datum_result)

    # 정북 일조사선 (2D multi-height lines + 3D envelope)
    if sunlight_applies and classified["north"]:
        result["north_setback"] = _compute_sunlight_setback_lines(
            classified["north"], parcel_utm, sunlight_rules,
        )
        result["sunlight_envelope"] = compute_sunlight_envelope(
            classified["north"], parcel_utm, sunlight_rules,
            datum=_sunlight_datum(datum_result),
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


def _maybe_compute_datum(
    parcel_wgs: Polygon,
    compute_datum: bool,
    road_frontages: list[dict] | None = None,
    neighbor_parcels: list[dict] | None = None,
    north_edges_utm: list[LineString] | None = None,
):
    """
    Phase 2B: 옵트인 datum 계산.

    실패 가능 모든 지점은 None 반환 → envelope이 datum 없이 정상 생성.
    LOCKED SPEC 시각 결과 보존 (datum 없으면 frontend는 terrain fallback).
    """
    if not compute_datum:
        return None
    try:
        from backend.app.modules.land.reference.services.datum import compute_datum_elevation, DatumContext
        return compute_datum_elevation(DatumContext(
            parcel_wgs=parcel_wgs,
            road_centerline_wgs=_datum_road_centerline(road_frontages),
            neighbor_parcel_wgs=_datum_neighbor_polygon(neighbor_parcels, north_edges_utm),
        ))
    except ValueError as e:
        logger.warning(f"datum compute skipped (invalid polygon): {e}")
        return None
    except Exception as e:
        # ElevationFetchError, etc — already handled internally as fallback,
        # but defend against unexpected errors anyway
        logger.warning(f"datum compute failed: {e}")
        return None


def _datum_road_centerline(road_frontages: list[dict] | None) -> LineString | None:
    if not road_frontages:
        return None
    candidates = []
    for idx, frontage in enumerate(road_frontages):
        coords = frontage.get("roadCenterline") or frontage.get("road_centerline")
        if coords and len(coords) >= 2:
            try:
                line = LineString(coords)
                width = float(frontage.get("roadWidthM") or frontage.get("road_width_m") or 0.0)
                shared = frontage.get("sharedEdge") or frontage.get("shared_edge")
                shared_len = 0.0
                if shared and len(shared) >= 2:
                    try:
                        shared_len = LineString([
                            _to_utm.transform(float(x), float(y)) for x, y in shared
                        ]).length
                    except Exception:
                        shared_len = 0.0
                candidates.append((width, shared_len, -idx, line))
            except Exception:
                continue
    if candidates:
        # Multiple road frontages are possible on corner lots. Use the primary
        # frontage for §119 road datum: widest road first, then longer shared
        # frontage. Per-edge building-line setbacks still use every road edge.
        candidates.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
        return candidates[0][3]
    return None


def _datum_neighbor_polygon(
    neighbor_parcels: list[dict] | None,
    north_edges_utm: list[LineString] | None = None,
) -> Polygon | None:
    if not neighbor_parcels:
        return None
    candidates = []
    for idx, neighbor in enumerate(neighbor_parcels):
        geom = neighbor.get("geometry")
        if not geom:
            continue
        try:
            poly = shape(geom)
            if isinstance(poly, MultiPolygon):
                poly = max(poly.geoms, key=lambda g: g.area)
            if isinstance(poly, Polygon) and not poly.is_empty and poly.is_valid:
                shared = neighbor.get("sharedEdge") or neighbor.get("shared_edge")
                shared_utm = None
                if shared and len(shared) >= 2:
                    try:
                        shared_utm = LineString([_to_utm.transform(float(x), float(y)) for x, y in shared])
                    except Exception:
                        shared_utm = None
                if shared_utm is not None:
                    midpoint_y = shared_utm.interpolate(0.5, normalized=True).y
                    north_distance = min((shared_utm.distance(edge) for edge in (north_edges_utm or [])), default=0.0)
                else:
                    poly_utm = _wgs_to_utm(poly)
                    midpoint_y = poly_utm.representative_point().y
                    north_distance = 999999.0 if north_edges_utm else 0.0
                candidates.append((north_distance, -midpoint_y, idx, poly))
        except Exception:
            continue
    if not candidates:
        return None
    # §86 uses the north-side neighboring lot. Prefer neighbors whose shared edge
    # coincides with the north-facing parcel edge, then the northernmost edge.
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    return candidates[0][3]
    return None


def _sunlight_datum(datum):
    """정북일조 envelope는 인접대지 평균수평면이 있으면 그 기준면을 사용한다."""
    if datum is None:
        return None
    neighbor_avg = getattr(datum, "neighbor_avg_datum_m", None)
    if neighbor_avg is None:
        return datum
    try:
        from backend.app.modules.land.reference.services.datum import DatumCase
        return replace(
            datum,
            elevation_m=float(neighbor_avg),
            case=DatumCase.NEIGHBOR_AVG_86,
            basis="neighbor_avg_86",
        )
    except Exception:
        return datum


def _datum_to_dict(datum) -> dict:
    """DatumResult → JSON-serializable dict (디버그용 setback_lines 출력)."""
    case = getattr(datum, "case", None)
    return {
        "elevation_m": float(getattr(datum, "elevation_m", 0.0)),
        "case": case.value if hasattr(case, "value") else None,
        "basis": getattr(datum, "basis", None),
        "elevation_source": getattr(datum, "elevation_source", None),
        "parcel_datum_m": getattr(datum, "parcel_datum_m", None),
        "road_datum_m": getattr(datum, "road_datum_m", None),
        "neighbor_datum_m": getattr(datum, "neighbor_datum_m", None),
        "neighbor_avg_datum_m": getattr(datum, "neighbor_avg_datum_m", None),
        "parcel_segments": getattr(datum, "parcel_segments", None),
        "road_samples": getattr(datum, "road_samples", None),
        "neighbor_segments": getattr(datum, "neighbor_segments", None),
        "split_bands": getattr(datum, "split_bands", None),
        "split_polygons": getattr(datum, "split_polygons", None),
        "notes": getattr(datum, "notes", None),
    }
