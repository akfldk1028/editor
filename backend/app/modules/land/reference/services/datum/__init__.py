"""
Datum elevation module — §119 / §86 datum (H=0) 계산.

`envelopes/sunlight.py` 등 envelope 모듈이 H=0 절대 표고를 알아야 정확한
법규 준수 envelope 생성 가능. Vworld는 표고 API 없어 Open-Meteo로 대체.

사용 예 (Phase 2에서 setback_geometry 가 호출):
    from land.services.datum import compute_datum_elevation, DatumContext
    result = compute_datum_elevation(DatumContext(parcel_wgs=parcel))
    # result.elevation_m → envelope walls/slanted_polygons에 절대 표고로 전달

수정 전 반드시 `memory/arr/datum-elevation/README.md` 읽을 것.
"""

from backend.app.modules.land.reference.services.datum.cases import DatumCase, DatumContext, DatumResult, compute_datum_elevation, FLAT_VARIANCE_THRESHOLD_M, SLOPE_3M_THRESHOLD_M, ROAD_SLOPE_THRESHOLD_M, MAX_PARCEL_VERTICES, ELEV_SOURCE_OPEN_METEO, ELEV_SOURCE_FAILED
from backend.app.modules.land.reference.services.datum.elevation_api import ElevationFetchError
from backend.app.modules.land.reference.services.datum import calculator, elevation_api

__all__ = [
    "DatumCase",
    "DatumContext",
    "DatumResult",
    "compute_datum_elevation",
    "ElevationFetchError",
    "FLAT_VARIANCE_THRESHOLD_M",
    "SLOPE_3M_THRESHOLD_M",
    "ROAD_SLOPE_THRESHOLD_M",
    "MAX_PARCEL_VERTICES",
    "ELEV_SOURCE_OPEN_METEO",
    "ELEV_SOURCE_FAILED",
    "calculator",
    "elevation_api",
]
