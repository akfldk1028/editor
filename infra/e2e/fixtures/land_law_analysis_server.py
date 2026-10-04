"""Actual Editor law-analysis pipeline with isolated HTTP/LLM fixtures."""
import json
import os
import httpx
import uvicorn
from fastapi import FastAPI

from backend.app.adapters.law_search import LawSearchClient
from backend.app.adapters.regulation_extraction import RegulationExtractionClient
from backend.app.api.routes_land import create_land_router
from backend.app.modules.land.repository import LandRepository


def provider(request):
    query = json.loads(request.content)['query']
    if query == '가각전제':
        return httpx.Response(503)
    return httpx.Response(200,json={'results':[{'hang_id':'fixture-1','law_name':'fixture law',
        'article':'1','jo_name':'1','content':'fixture law evidence','similarity':.95,
        'source_reference':{'document':'fixture evidence only'}}]})


async def complete(**kwargs):
    return json.dumps({'adjacent_setback_m':999})


search = LawSearchClient('https://fixture.invalid',transport=httpx.MockTransport(provider))
extraction = RegulationExtractionClient(search,enabled=True,api_key='fixture-only',completion=complete)
app = FastAPI()
app.include_router(create_land_router( public_origin='http://127.0.0.1:5186',
    repository=LandRepository(os.environ['EDITOR_LAND_DATA_DIR']),law_client=search,extraction_client=extraction))

if __name__ == '__main__':
    uvicorn.run(app,host='127.0.0.1',port=18440)
