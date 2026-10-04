"""Actual Editor datum pipeline with isolated external HTTP and storage fixtures."""
import os
import httpx
import uvicorn
from fastapi import FastAPI

from backend.app.adapters.elevation import ElevationClient
from backend.app.adapters.vworld import VworldClient
from backend.app.adapters.vworld_land import VworldLandClient
from backend.app.adapters.vworld_geometry import VworldGeometryClient
from backend.app.api.routes_land import create_land_router
from backend.app.modules.land.datum import DatumService
from backend.app.modules.land.repository import LandRepository


def vworld(request):
    if '/ned/' in request.url.path:
        if request.url.path.endswith('getLandUseAttr'):
            return httpx.Response(200,json={'landUses':{'field':[{'prposAreaDstrcCodeNm':'제2종일반주거지역','cnflcAtNm':'포함'}]}})
        if request.url.path.endswith('ladfrlList'):
            return httpx.Response(200,json={'ladfrlVOList':{'ladfrlVOList':[{'lndpclAr':'900'}]}})
        return httpx.Response(200,json={'indvdLandPrices':{'field':[{'pblntfPclnd':'1200'}]}})
    features=[]
    if 'attrFilter' in request.url.params:
        failed=request.url.params['attrFilter'].endswith('0004')
        x=127.01 if failed else 127
        geometry={'type':'Polygon','coordinates':[[[x,37],[x+.0004,37],[x+.0004,37.0005],[x,37.0005],[x,37]]]}
        features=[{'type':'Feature','geometry':geometry,'properties':{}}]
    return httpx.Response(200,json={'response':{'status':'OK','result':{'featureCollection':{'features':features}}}})


def elevation(request):
    longitudes=request.url.params['longitude'].split(',')
    if float(longitudes[0])>127.005:
        return httpx.Response(503)
    return httpx.Response(200,json={'elevation':[12.5]*len(longitudes)})


os.environ['ENABLE_DATUM_ELEVATION']='true'
transport=httpx.MockTransport(vworld)
app=FastAPI()
app.include_router(create_land_router(public_origin='http://127.0.0.1:5186',
    address_client=VworldClient('fixture-only',transport=transport),
    repository=LandRepository(os.environ['EDITOR_LAND_DATA_DIR']),
    attribute_client=VworldLandClient('fixture-only',transport=transport,year=2026),
    geometry_client=VworldGeometryClient('fixture-only',transport=transport),
    datum_service_factory=lambda:DatumService(ElevationClient(transport=httpx.MockTransport(elevation)))))

if __name__=='__main__':
    uvicorn.run(app,host='127.0.0.1',port=18441)
