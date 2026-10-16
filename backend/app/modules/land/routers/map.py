import logging
import math
import os
import json
from fastapi import APIRouter, HTTPException, Request, Response
import asyncio

from backend.app.adapters import scene_agent, site_context
from backend.app.modules.platform import host
from backend.app.modules.land.vworld.map import MapUnavailable, VworldMapClient

logger = logging.getLogger(__name__)


def create_land_map_router(client=None, *, prefix='/api/v1/land'):
    provider = client or VworldMapClient(os.environ.get('VWORLD_API_KEY', ''))
    router = APIRouter(prefix=prefix, tags=['land-map'])
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

    async def context(ask, lat, lon, radius_m):
        if not (33 <= lat <= 39 and 124 <= lon <= 132) or not 10 <= radius_m <= 1000:
            raise HTTPException(422, 'lat/lon must be in Korea and radius_m 10..1000')
        # SceneAgent is stopped by the host when idle: the map's call brings it up first (lazy activation, the same
        # door the law analysis uses) instead of reporting it unreachable. A missing host is not an error here.
        # Right after a stop the host can still answer "up" from its last tick, so one refused call is asked again.
        for attempt in (1, 2):
            try:
                await host.ensure(['scene'])
            except (host.HostUnavailable, host.HostRefused):
                pass
            try:
                return await asyncio.to_thread(ask, lat, lon, radius_m)
            except scene_agent.SceneAgentError as error:
                if attempt == 2:
                    raise HTTPException(502, str(error)) from None

    @router.get('/terrain-heights')
    async def terrain_heights(west: float, south: float, east: float, north: float, size: int = 17):
        """A size x size height grid over a box (rows north to south, columns west to east) from SiteContext's
        NGII DEM - the world view's terrain tiles. All heights or a refusal, never a partial grid."""
        if not (124 <= west < east <= 132 and 33 <= south < north <= 39) or east - west > 0.1 or north - south > 0.1                 or not 2 <= size <= 33:
            raise HTTPException(422, 'box must be in Korea, at most 0.1 deg a side; size 2..33')
        points = [(north - r * (north - south) / (size - 1), west + c * (east - west) / (size - 1))
                  for r in range(size) for c in range(size)]
        try:
            heights, dataset = await asyncio.to_thread(site_context.ground_heights, points)
        except site_context.SiteHeightsError as error:
            raise HTTPException(502, str(error)) from None
        return {'size': size, 'heights': [round(h, 2) for h in heights], 'dataset': dataset}

    @router.get('/context-buildings')
    async def context_buildings(lat: float, lon: float, radius_m: float = 300.0):
        """White context masses around a point (SceneAgent: SiteContext footprints + height rule) - no VWorld SDK needed."""
        return await context(scene_agent.context_buildings, lat, lon, radius_m)

    @router.get('/context-ground')
    async def context_ground(lat: float, lon: float, radius_m: float = 300.0):
        """The ground around a point: cadastral parcels by 지목 class and carriageways (SceneAgent over SiteContext)."""
        return await context(scene_agent.context_ground, lat, lon, radius_m)

    return router
