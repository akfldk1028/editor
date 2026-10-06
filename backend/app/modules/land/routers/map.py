import logging
import math
import os
import json
from fastapi import APIRouter, HTTPException, Request, Response
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

    return router
