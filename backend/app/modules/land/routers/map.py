import logging
import math
import os
import json
import time
from fastapi import APIRouter, HTTPException, Request, Response
import asyncio
from collections import OrderedDict
from typing import Literal

from backend.app.adapters import scene_agent
from backend.app.adapters.elevation import ElevationFetchError, ElevationMissingSamples
from backend.app.modules.platform import host
from backend.app.modules.land.vworld.map import MapUnavailable, VworldMapClient
from backend.app.modules.land import building_tiles, map_terrain, map_roads, map_ground

logger = logging.getLogger(__name__)


def create_land_map_router(client=None, *, prefix='/api/v1/land'):
    provider = client or VworldMapClient(os.environ.get('VWORLD_API_KEY', ''))
    router = APIRouter(prefix=prefix, tags=['land-map'])
    roads = map_roads.RoadDisplay()
    ground = map_ground.GroundDisplay(roads)
    if os.environ.get('VWORLD_BROWSER_API_KEY') and os.environ.get('VWORLD_BROWSER_API_KEY') == os.environ.get('VWORLD_API_KEY'):
        # map-config hands this key to every browser; it must not be the server key.
        logger.warning('VWORLD_BROWSER_API_KEY equals VWORLD_API_KEY; issue a separate key restricted to the editor origin')

    @router.get('/map-config')
    async def map_config():
        browser_key = os.environ.get('VWORLD_BROWSER_API_KEY', '')
        if not browser_key:
            raise HTTPException(503, 'VWorld 3D 지도가 설정되지 않았습니다.')
        return Response(content=json.dumps({'api_key': browser_key}),
                        media_type='application/json', headers={'Cache-Control': 'no-store'})

    async def image(operation, max_age):
        try:
            return Response(await operation, media_type='image/png', headers={'Cache-Control': f'public, max-age={max_age}'})
        except MapUnavailable as error:
            raise HTTPException(503 if not provider.api_key else 502, str(error)) from None

    @router.get('/tiles/{z}/{y}/{x}.png')
    async def tile(z: int, y: int, x: int):
        if not 0 <= z <= 19 or not 0 <= x < 2**z or not 0 <= y < 2**z:
            raise HTTPException(422, 'Invalid map tile coordinates')
        return await image(provider.tile(z, y, x), 86400)

    @router.get('/wms')
    async def wms(request: Request):
        query = {key.upper(): value for key, value in request.query_params.items()}
        try:
            bbox = [float(value) for value in query.get('BBOX', '').split(',')]
            width, height = int(query.get('WIDTH', '256')), int(query.get('HEIGHT', '256'))
            layers = query.get('LAYERS', 'lp_pa_cbnd_bonbun,lp_pa_cbnd_bubun')
            if len(bbox) != 4 or any(not math.isfinite(v) or abs(v) > 20037509 for v in bbox):
                raise ValueError()
            if bbox[0] >= bbox[2] or bbox[1] >= bbox[3] or not 1 <= width <= 2048 or not 1 <= height <= 2048:
                raise ValueError()
            if not set(layers.split(',')) <= {'lp_pa_cbnd_bonbun', 'lp_pa_cbnd_bubun'} or query.get('CRS', 'EPSG:3857') != 'EPSG:3857':
                raise ValueError()
        except ValueError:
            raise HTTPException(422, 'Invalid cadastral map parameters') from None
        params = {'SERVICE': 'WMS', 'REQUEST': 'GetMap', 'VERSION': '1.3.0', 'CRS': 'EPSG:3857',
                  'BBOX': ','.join(map(str, bbox)), 'WIDTH': width, 'HEIGHT': height,
                  'LAYERS': layers, 'FORMAT': 'image/png', 'TRANSPARENT': 'true'}
        return await image(provider.wms(params), 300)

    lease_task = None
    leased_at = float('-inf')

    async def lease_scene():
        nonlocal leased_at
        try:
            result = await host.ensure(['scene'])
            if result.get('failed'):
                raise host.HostRefused(str(result['failed']))
            leased_at = time.monotonic()
        except (host.HostUnavailable, host.HostRefused):
            logger.warning('scene lease not renewed', exc_info=True)

    def renew_scene(*, force=False):
        nonlocal lease_task
        if lease_task is not None and not lease_task.done():
            return lease_task
        if force or time.monotonic() - leased_at >= 60:
            lease_task = asyncio.create_task(lease_scene())
            return lease_task
        return None

    async def context(ask, lat, lon, radius_m):
        if not (33 <= lat <= 39 and 124 <= lon <= 132) or not 10 <= radius_m <= 1000:
            raise HTTPException(422, 'lat/lon must be in Korea and radius_m 10..1000')
        # A live service answers directly. All visible cells share one background
        # lease renewal; only an unavailable service puts activation on the path.
        renew_scene()
        for attempt in (1, 2):
            try:
                return await asyncio.to_thread(ask, lat, lon, radius_m)
            except scene_agent.SceneAgentError as error:
                if attempt == 2:
                    raise HTTPException(502, str(error)) from None
                await asyncio.shield(renew_scene(force=True))

    # Shared across browsers, bounded and short-lived so refreshed source DEMs
    # replace old grids. Failed/partial samples never enter this display cache.
    terrain_cache = OrderedDict()
    terrain_pending = {}

    async def sample_grid(key, points, size):
        try:
            heights, dataset = await asyncio.to_thread(map_terrain.ground_heights, points)
            result = {'size': size, 'heights': [round(h, 2) for h in heights], 'dataset': dataset}
            terrain_cache[key] = (time.monotonic(), result)
            terrain_cache.move_to_end(key)
            while len(terrain_cache) > 256:
                terrain_cache.popitem(last=False)
            return result
        finally:
            terrain_pending.pop(key, None)

    @router.get('/terrain-revision')
    async def terrain_revision():
        try:
            metadata = await asyncio.to_thread(map_terrain.metadata)
        except ElevationFetchError as error:
            raise HTTPException(503, str(error)) from None
        return Response(content=json.dumps(metadata), media_type='application/json',
                        headers={'Cache-Control': 'no-store'})

    @router.get('/terrain-heights')
    async def terrain_heights(west: float, south: float, east: float, north: float, size: int = 17):
        """Local NGII grid, rows north to south. Missing cells fail the whole grid."""
        if not (124 <= west < east <= 132 and 33 <= south < north <= 39) or east - west > 0.1 or north - south > 0.1                 or not 2 <= size <= 33:
            raise HTTPException(422, 'box must be in Korea, at most 0.1 deg a side; size 2..33')
        points = [(north - r * (north - south) / (size - 1), west + c * (east - west) / (size - 1))
                  for r in range(size) for c in range(size)]
        try:
            source = await asyncio.to_thread(map_terrain.identity)
        except ElevationFetchError as error:
            raise HTTPException(502, str(error)) from None
        key = (source, west, south, east, north, size)
        cached = terrain_cache.get(key)
        if cached and time.monotonic() - cached[0] < 900:
            terrain_cache.move_to_end(key)
            return cached[1]
        if key not in terrain_pending:
            task = asyncio.create_task(sample_grid(key, points, size))
            terrain_pending[key] = task
            # A disconnected browser must not cancel another browser's grid.
            task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
        try:
            return await asyncio.shield(terrain_pending[key])
        except ElevationMissingSamples as error:
            raise HTTPException(404, str(error)) from None
        except ElevationFetchError as error:
            raise HTTPException(502, str(error)) from None

    @router.get('/context-tiles')
    async def context_tiles(request: Request):
        base = request.url.path.removesuffix('/context-tiles')
        return await asyncio.to_thread(building_tiles.latest, base)

    @router.head('/building-tiles/{version}/buildings.pmtiles', include_in_schema=False)
    @router.get('/building-tiles/{version}/buildings.pmtiles')
    async def building_archive(version: str):
        return building_tiles.response(version)

    @router.get('/context-buildings')
    async def context_buildings(lat: float, lon: float, radius_m: float = 300.0):
        """White context masses around a point (SceneAgent: SiteContext footprints + height rule) - no VWorld SDK needed."""
        return await context(scene_agent.context_buildings, lat, lon, radius_m)

    @router.get('/context-ground')
    async def context_ground(lat: float, lon: float, radius_m: float = 300.0, detail: Literal['full', 'roads'] = 'full'):
        """Cadastral ground and land cover from providers, carriageways from installed sources."""
        if not (33 <= lat <= 39 and 124 <= lon <= 132) or not 10 <= radius_m <= 1000:
            raise HTTPException(422, 'lat/lon must be in Korea and radius_m 10..1000')
        try:
            return await (roads if detail == 'roads' else ground).get(lat, lon, radius_m)
        except (map_roads.RoadsUnavailable, map_ground.SourceUnavailable) as error:
            raise HTTPException(503, str(error)) from None

    return router
