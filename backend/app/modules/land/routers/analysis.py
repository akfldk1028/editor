import os
import sqlite3
from typing import Annotated, Literal
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, model_validator
from backend.app.modules.regulations.zoning_catalog import CatalogUnavailable, get_zones
from backend.app.modules.land.pnu import normalize_pnu, parse_pnu
from backend.app.schemas.regulations import ZoningLimitsRequest
from backend.app.modules.land.agent_analysis import agent_analysis_events, configured_team, sse
from backend.app.modules.land.analysis_request import normalize_program_request
from backend.app.modules.land.parcel_geometry import parcel_geometry
from backend.app.modules.land.services import DatumConfigurationError, LandServices
from backend.app.modules.land.routers.map import create_land_map_router
from backend.app.modules.land.routers.selections import create_land_selections_router


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
                       datum_service_factory=None, services=None, agent_team=None, agent_environment=None):
    origin=public_origin or os.environ.get('EDITOR_PUBLIC_URL','http://127.0.0.1:5173')
    router=APIRouter(prefix='/api/v1/land',tags=['land'])
    services = services or LandServices.from_environment(
        address_client=address_client, repository=repository, attribute_client=attribute_client,
        geometry_client=geometry_client, law_client=law_client, extraction_client=extraction_client,
        datum_service_factory=datum_service_factory)
    addresses = services.addresses

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
            local = services.local_repository()
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
            result = await services.analyze(body.model_dump())
            return {**result, 'execution_owner': 'editor'}
        except DatumConfigurationError:
            raise HTTPException(503, 'Datum configuration unavailable') from None
        except (CatalogUnavailable, OSError):
            raise HTTPException(503, 'Regulation references unavailable') from None

    @router.get('/agent-analyze/stream')
    async def agent_analyze_stream(request: Request, pnu: str = Query(default='', max_length=100),
                                   address: str = Query(default='', max_length=500),
                                   zones: str = Query(default='', max_length=2000)):
        # Quick analysis first, then the saved land team runs in-process; see modules/land/agent_analysis.py.
        check_origin(request)
        pnu, address = pnu.strip(), address.strip()
        if not pnu and not address:
            raise HTTPException(422, 'pnu or address is required')
        if pnu:
            try:
                pnu = normalize_pnu(pnu)
            except ValueError as error:
                raise HTTPException(422, str(error)) from None
        team, environment = configured_team(agent_team, agent_environment)
        events = agent_analysis_events(pnu=pnu, address=address, services=services, team=team,
                                       environment=environment,
                                       zones=[zone.strip() for zone in zones.split(',') if zone.strip()])
        return StreamingResponse((sse(event) async for event in events), media_type='text/event-stream',
                                 headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})

    router.include_router(create_land_map_router(prefix=''))
    router.include_router(create_land_selections_router(services, check_origin))
    return router
