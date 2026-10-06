"""Isolated browser fixture: actual Editor routes, no external provider or ARR."""
import httpx
import uvicorn
from fastapi import FastAPI
from backend.app.modules.land.vworld import VworldClient
from backend.app.modules.land.routers.analysis import create_land_router


def provider(request):
    if request.url.path.endswith('/address'):
        return httpx.Response(200,json={'response':{'status':'OK','result':[{'text':'Fixture parcel address'}]}})
    return httpx.Response(200,json={'response':{'status':'OK','result':{'featureCollection':{'features':[{
        'properties':{'pnu':'1168011200101280003'},
        'geometry':{'type':'Polygon','coordinates':[
            [[127,37],[127.01,37],[127.01,37.01],[127,37.01],[127,37]],
            [[127.002,37.002],[127.004,37.002],[127.004,37.004],[127.002,37.004],[127.002,37.002]]
        ]}}]}}}})


app=FastAPI()
app.include_router(create_land_router(public_origin='http://127.0.0.1:5186',
    address_client=VworldClient('fixture-only',transport=httpx.MockTransport(provider))))

if __name__=='__main__':
    uvicorn.run(app,host='127.0.0.1',port=18436)
