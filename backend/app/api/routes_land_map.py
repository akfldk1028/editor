import math
import os
from fastapi import APIRouter, HTTPException, Request, Response
from backend.app.adapters.vworld_map import MapUnavailable, VworldMapClient


def create_land_map_router(client=None, *, prefix='/api/v1/land'):
    provider = client or VworldMapClient(os.environ.get('VWORLD_API_KEY', ''))
    router = APIRouter(prefix=prefix, tags=['land-map'])

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
