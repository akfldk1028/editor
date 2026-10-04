import os
import sqlite3
from typing import Annotated, Literal
from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, model_validator
from backend.app.modules.regulations.zoning_catalog import CatalogUnavailable, get_zones
from backend.app.modules.land.pnu import normalize_pnu, parse_pnu
from backend.app.adapters.vworld import VworldClient
from backend.app.adapters.vworld_land import VworldLandClient
from backend.app.adapters.vworld_geometry import VworldGeometryClient
from backend.app.adapters.law_search import LawSearchClient
from backend.app.adapters.regulation_extraction import RegulationExtractionClient
from backend.app.adapters.elevation import ElevationClient
from backend.app.modules.land.datum import DatumService, DatumSettings
from backend.app.schemas.regulations import ZoningLimitsRequest
from backend.app.modules.land.analysis import analyze_land
from backend.app.modules.land.analysis_request import normalize_program_request
from backend.app.modules.land.parcel_geometry import parcel_geometry
from backend.app.modules.land.attributes import LandAttributes
from backend.app.modules.land.repository import LandRepository


class LandRequest(BaseModel):
    model_config=ConfigDict(strict=True,extra='forbid',allow_inf_nan=False)
    input: str=Field(max_length=500)
    input_type: Literal['address','pnu','raw']
    zones: list[Annotated[str,Field(min_length=1,max_length=100)]]=Field(default_factory=list,max_length=50)
    include_law: bool=True
    geometry: dict | None=None
    building_type: str=Field(default='',max_length=200)
    floor_area_m2: float | None=Field(default=None,gt=0)
    program_uses: list[dict] | None=Field(default=None,min_length=1,max_length=100)
    assessment_date: str | None=None

    @model_validator(mode='after')
    def check_input(self):
        self.input=self.input.strip()
        if self.input_type=='pnu':
            self.input=normalize_pnu(self.input)
        if self.input_type=='raw':
            if not self.zones: raise ValueError('zones are required')
        elif not self.input:
            raise ValueError('input is required')
        for name, value in normalize_program_request(self.model_dump()).items():
            setattr(self, name, value)
        if self.geometry is not None:
            self.geometry = parcel_geometry(self.geometry)
        return self


class ResolutionRequest(BaseModel):
    model_config=ConfigDict(strict=True, extra='forbid')
    input: str=Field(min_length=1, max_length=500)
    input_type: Literal['address', 'pnu']='pnu'

    @model_validator(mode='after')
    def check_input(self):
        self.input=self.input.strip()
        if not self.input: raise ValueError('input is required')
        if self.input_type=='pnu': self.input=normalize_pnu(self.input)
        return self


class ReverseRequest(BaseModel):
    model_config=ConfigDict(strict=True, extra='forbid', allow_inf_nan=False)
    x: float=Field(ge=124, le=133)
    y: float=Field(ge=33, le=44)


class ParcelRequest(BaseModel):
    model_config=ConfigDict(strict=True, extra='forbid')
    pnu: str=Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def check_pnu(self):
        self.pnu=normalize_pnu(self.pnu)
        return self


def create_land_router(*, public_origin=None, address_client=None, repository=None,
                       attribute_client=None, geometry_client=None, law_client=None, extraction_client=None,
                       datum_service_factory=None):
    origin=public_origin or os.environ.get('EDITOR_PUBLIC_URL','http://127.0.0.1:5173')
    router=APIRouter(prefix='/api/v1/land',tags=['land'])
    addresses=address_client or VworldClient(os.environ.get('VWORLD_API_KEY', ''))
    attributes=attribute_client or VworldLandClient(os.environ.get('VWORLD_API_KEY', ''))
    geometries=geometry_client or VworldGeometryClient(os.environ.get('VWORLD_API_KEY', ''))
    laws=law_client or LawSearchClient(os.environ.get('LAW_BACKEND_URL'), os.environ.get('AG_LIGHT_URL'))
    extraction=extraction_client or RegulationExtractionClient(laws,
        enabled=os.environ.get('LLM_EXTRACTION_ENABLED', 'false').lower() == 'true',
        api_key=os.environ.get('OPENAI_API_KEY', ''),
        model=os.environ.get('LLM_EXTRACTION_MODEL', 'gpt-4o-mini'))
    datum_enabled = os.environ.get('ENABLE_DATUM_ELEVATION', 'false').lower() == 'true'
    datum_environment = {name: os.environ.get(name, default) for name, default in {
        'ELEVATION_PROVIDER': 'open_meteo', 'NGII_LIDAR_URL': 'http://localhost:5000',
        'NGII_DEM_LOCAL_PATH': '', 'DATUM_EDGE_SUBSAMPLE': 'true',
        'DATUM_EDGE_SUBSAMPLE_THRESHOLD_M': '10.0', 'DATUM_EDGE_SUBSAMPLE_STEP_M': '5.0',
        'DATUM_MEDIAN_FILTER': 'true', 'DATUM_MEDIAN_FILTER_WINDOW': '3',
    }.items()}

    def new_datum_service():
        if not datum_enabled:
            return None
        if datum_service_factory is not None:
            return datum_service_factory()
        settings = DatumSettings(
            edge_subsample=datum_environment['DATUM_EDGE_SUBSAMPLE'].lower() == 'true',
            edge_subsample_threshold_m=float(datum_environment['DATUM_EDGE_SUBSAMPLE_THRESHOLD_M']),
            edge_subsample_step_m=float(datum_environment['DATUM_EDGE_SUBSAMPLE_STEP_M']),
            median_filter=datum_environment['DATUM_MEDIAN_FILTER'].lower() == 'true',
            median_filter_window=int(datum_environment['DATUM_MEDIAN_FILTER_WINDOW']))
        provider = ElevationClient(datum_environment['ELEVATION_PROVIDER'],
            opentopodata_url=datum_environment['NGII_LIDAR_URL'],
            local_dem_path=datum_environment['NGII_DEM_LOCAL_PATH'], timeout=5)
        return DatumService(provider, settings)

    def local_repository():
        if repository is not None:
            return repository
        directory = os.environ.get('EDITOR_LAND_DATA_DIR')
        return LandRepository(directory) if directory else None

    def check_origin(request):
        if request.headers.get('sec-fetch-site')=='cross-site' or (request.headers.get('origin') and request.headers['origin']!=origin):
            raise HTTPException(403,'Cross-origin analysis is not allowed')

    @router.post('/resolve')
    async def resolve(body: ResolutionRequest, request: Request):
        check_origin(request)
        if body.input_type=='pnu':
            return {'valid':True, 'parsed':parse_pnu(body.input)}
        return await addresses.resolve_address(body.input)

    @router.post('/reverse')
    async def reverse(body: ReverseRequest, request: Request):
        check_origin(request)
        return await addresses.reverse_geocode(body.x, body.y)

    @router.post('/parcel-geometry')
    async def geometry(body: ParcelRequest, request: Request):
        check_origin(request)
        return await addresses.fetch_parcel_geometry(body.pnu)

    @router.get('/zones')
    def zones():
        try:
            return get_zones()
        except CatalogUnavailable:
            raise HTTPException(503, 'Zoning catalog unavailable') from None

    @router.get('/stats')
    async def stats(scope: Literal['all', 'imported', 'editor'] = 'all'):
        try:
            local = local_repository()
            if local is None:
                raise HTTPException(503, 'Land storage is not configured')
            return {**await run_in_threadpool(local.stats, scope),
                    'scope': {'all':'editor_all', 'imported':'editor_imported', 'editor':'editor_local'}[scope],
                    'legacy_history_included': scope != 'editor'}
        except (OSError, ValueError, sqlite3.Error):
            raise HTTPException(503, 'Land statistics unavailable') from None

    @router.post('/zoning-limits')
    def zoning_limits(body: ZoningLimitsRequest, request: Request):
        from backend.app.modules.regulations.zoning_limits import resolve_limits
        check_origin(request)
        try:
            known={zone['zone_name'] for zone in get_zones()['zones']}
            if body.zone_areas is not None and not set(body.zones)<=known:
                raise HTTPException(422,'Area split contains an unknown zone')
            return {'limits':resolve_limits(body.zones,body.zone_areas),
                'scope':'national_reference','permit_compliance_verified':False}
        except CatalogUnavailable:
            raise HTTPException(503,'Zoning reference unavailable') from None

    @router.post('/analyze')
    async def analyze(body: LandRequest, request: Request):
        check_origin(request)
        try:
            local = local_repository()
        except (OSError, ValueError):
            local = None
        try:
            datum_service = new_datum_service()
        except (ValueError, OSError):
            raise HTTPException(503, 'Datum configuration unavailable') from None
        try:
            result = await analyze_land(body.model_dump(), addresses,
                LandAttributes(attributes, local), geometries, local,
                law_client=laws, extraction_client=extraction, datum_service=datum_service)
            return {**result, 'execution_owner': 'editor'}
        except (CatalogUnavailable, OSError):
            raise HTTPException(503, 'Regulation references unavailable') from None

    return router
