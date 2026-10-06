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

from shapely.geometry import MultiPolygon, Polygon, shape

from .sunlight_envelope import compute_sunlight_envelope
from .setbacks_edges import (
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
    _compute_sunlight_setback_lines,
    _offset_edges_inward,
    _offset_edges_with_distances_inward,
)
from .setbacks_daylight import (
    _compute_daylight_diagonal_envelope,
    _daylight_reference_surface_shells,
    _densify_ring,
    _daylight_reference_edges,
)
from .setbacks_corner import (
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
    datum_service=None,
) -> dict:
    """
    필지 polygon + 규제 수치 → 규제선 GeoJSON dict.

    Args:
        parcel_geojson: GeoJSON geometry (Polygon from Vworld)
        regulations: regulation_calculator.calculate_all() 결과
        compute_datum: True requests an explicitly supplied datum service.
            Relative envelope heights remain unchanged.
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
    if compute_datum and datum_service is None:
        raise ValueError("Enabled datum requires an explicit service")
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
    datum = None
    if compute_datum:
        from backend.app.modules.land.datum import DatumContext, DatumResult, DatumCase
        from backend.app.modules.land.datum.context_geometry import road_centerline, neighbor_polygon
        try:
            datum = datum_service.compute(DatumContext(parcel_wgs=parcel,
                road_centerline_wgs=road_centerline(road_frontages),
                neighbor_parcel_wgs=neighbor_polygon(neighbor_parcels, classified['north'])))
        except ValueError:
            datum = DatumResult(elevation_m=None, case=DatumCase.FLAT,
                basis='datum_context_unavailable', elevation_source='failed',
                notes=['Geometry exceeds datum calculation constraints; absolute datum was not applied'])
        result['datum_result'] = _datum_to_dict(datum)

    # 정북 일조사선 (2D multi-height lines + 3D envelope)
    if sunlight_applies and classified["north"]:
        result["north_setback"] = _compute_sunlight_setback_lines(
            classified["north"], parcel_utm, sunlight_rules,
        )
        result["sunlight_envelope"] = compute_sunlight_envelope(
            classified["north"], parcel_utm, sunlight_rules,
            datum=_sunlight_datum(datum),
        )
        if datum is not None and datum.elevation_source == 'failed' and result['sunlight_envelope']:
            result['sunlight_envelope'].update(datum_elevation_m=None, elevation_source='failed')

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


def _sunlight_datum(datum):
    if datum is None or datum.elevation_source == 'failed':
        return None
    if datum.neighbor_avg_datum_m is not None:
        from backend.app.modules.land.datum import DatumCase
        return replace(datum, elevation_m=float(datum.neighbor_avg_datum_m),
            case=DatumCase.NEIGHBOR_AVG_86, basis='neighbor_avg_86')
    return datum


def _datum_to_dict(datum):
    fields = ('elevation_m','basis','elevation_source','parcel_datum_m','road_datum_m',
        'neighbor_datum_m','neighbor_avg_datum_m','parcel_segments','road_samples',
        'neighbor_segments','split_bands','split_polygons','notes','provenance')
    return {**{key:getattr(datum,key,None) for key in fields}, 'case':datum.case.value}
