"""Actual Editor analysis with deterministic external HTTP responses and isolated DB."""
import os
import httpx
import uvicorn
from fastapi import FastAPI

from backend.app.adapters.land import LandClient
from backend.app.adapters.vworld import VworldClient
from backend.app.adapters.vworld_land import VworldLandClient
from backend.app.adapters.vworld_geometry import VworldGeometryClient
from backend.app.api.routes_land import create_land_router
from backend.app.modules.land.repository import LandRepository

PNU = '1168011200101280003'
CACHED_PNU = '1168011200101280004'
GEOMETRY = {'type':'Polygon','coordinates':[[[127,37],[127.001,37],[127.001,37.001],[127,37.001],[127,37]]]}
ZONE = '제2종일반주거지역'


def provider(request):
    path = request.url.path
    if '/ned/' in path:
        if request.url.params.get('pnu') == CACHED_PNU:
            return httpx.Response(503)
        if path.endswith('getLandUseAttr'):
            return httpx.Response(200,json={'landUses':{'field':[{'prposAreaDstrcCodeNm':ZONE,'cnflcAtNm':'포함'}]}})
        if path.endswith('ladfrlList'):
            return httpx.Response(200,json={'ladfrlVOList':{'ladfrlVOList':[{'lndpclAr':'900','lndcgrCodeNm':'대'}]}})
        return httpx.Response(200,json={'indvdLandPrices':{'field':[{'pblntfPclnd':'1200'}]}})
    if path.endswith('/address'):
        return httpx.Response(200,json={'response':{'status':'OK','result':{'point':{'x':'127','y':'37'}},
            'refined':{'text':'fixture address','structure':{'level4LC':PNU}}}})
    features = []
    if 'attrFilter' in request.url.params:
        features = [{'type':'Feature','geometry':GEOMETRY,'properties':{'pnu':PNU}}]
    if request.url.params.get('data') == 'LT_C_UQ111':
        features = [{'type':'Feature','geometry':GEOMETRY,'properties':{'uname':ZONE}}]
    return httpx.Response(200,json={'response':{'status':'OK','result':{'featureCollection':{'features':features}}}})


repository = LandRepository(os.environ['EDITOR_LAND_DATA_DIR'])
repository.put_land_cache(CACHED_PNU, {'success':True,'pnu':CACHED_PNU,'zones':[ZONE],
    'land_area_m2':900,'official_land_price':1200,'land_use_situation':'대',
    'source':'vworld','zones_fetched':True})
transport = httpx.MockTransport(provider)
app = FastAPI()
app.include_router(create_land_router(LandClient(None), public_origin='http://127.0.0.1:5186',
    repository=repository, address_client=VworldClient('fixture-only',transport=transport),
    attribute_client=VworldLandClient('fixture-only',transport=transport,year=2026),
    geometry_client=VworldGeometryClient('fixture-only',transport=transport)))

if __name__ == '__main__':
    uvicorn.run(app,host='127.0.0.1',port=18439)
