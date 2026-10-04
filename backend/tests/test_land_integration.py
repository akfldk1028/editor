import asyncio
import httpx
import pytest

from backend.app.adapters.land import LandClient, LandContractError, LandUnavailable


def payload(articles):
    return {'pnu':None,'regulations':None,'zone_info':None,'land_info':None,
        'law_articles':{'articles':articles,'total_count':1,'errors':['partial search']},
        'restrictions':[], 'warning':'incomplete sources'}


@pytest.mark.parametrize('grouped',[False,True])
def test_land_law_articles_accept_current_flat_and_legacy_grouped_contract(grouped):
    article={'hang_id':'a','content':'text','law_name':'law','article':'1'}
    values=[{'query':'zone','results':[article]}] if grouped else [article]
    client=LandClient('http://arr',transport=httpx.MockTransport(lambda r:httpx.Response(200,json=payload(values))))
    result=asyncio.run(client.analyze({'input':'zone','input_type':'raw'}))
    assert result['law_articles']['articles']==[article]
    assert result['law_articles']['errors']==['partial search']
    assert result['warning']=='incomplete sources'
    assert result['pnu'] is None


def test_land_bad_contract_and_unavailable_are_distinct():
    for response, error in [(httpx.Response(200,text='bad'),LandContractError),
        (httpx.Response(200,json={'success':True}),LandContractError),
        (httpx.Response(503),LandUnavailable)]:
        client=LandClient('http://arr',transport=httpx.MockTransport(lambda r:response))
        with pytest.raises(error): asyncio.run(client.analyze({'input':'x','input_type':'address'}))


def test_land_stats_rejects_malformed_breakdown():
    value={'total_queries':1,'avg_response_time_ms':1,'error_count':0,'by_input_type':[None]}
    client=LandClient('http://arr',transport=httpx.MockTransport(lambda r:httpx.Response(200,json=value)))
    with pytest.raises(LandContractError): asyncio.run(client.stats())


def test_land_preserves_owner_assessment_and_missing_evidence():
    value=payload([])
    value['assessment']={'status':'needs_evidence','permit_compliance_verified':False,
        'scope':'regulation_lookup_and_partial_calculation','missing_evidence':['municipal coverage'],
        'municipal_coverage':{'complete':False},'use_permission':{'status':'unknown'}}
    client=LandClient('http://arr',transport=httpx.MockTransport(lambda r:httpx.Response(200,json=value)))
    result=asyncio.run(client.analyze({'input':'x','input_type':'address'}))
    assert result['assessment']==value['assessment']


def test_land_analysis_timeout_allows_owner_partial_law_response():
    def handler(request):
        assert request.extensions['timeout']['read'] >= 150
        return httpx.Response(200,json=payload([]))
    client=LandClient('http://arr',transport=httpx.MockTransport(handler))
    asyncio.run(client.analyze({'input':'x','input_type':'address'}))


def test_land_route_validates_input_and_origin_before_owner_call():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.app.api.routes_land import create_land_router
    sent=[]
    def handler(request):
        sent.append(request)
        return httpx.Response(200,json=payload([]))
    app=FastAPI();app.include_router(create_land_router(LandClient('http://arr',transport=httpx.MockTransport(handler))))
    client=TestClient(app)
    for body in [{'input':'','input_type':'address'}, {'input':'bad','input_type':'pnu'},
        {'input':'x','input_type':'address','url':'http://other'}]:
        assert client.post('/api/v1/land/analyze',json=body).status_code==422
    body={'input':'11680-11200-10128-0003','input_type':'pnu','include_law':False}
    assert client.post('/api/v1/land/analyze',json=body,headers={'Origin':'https://other.example'}).status_code==403
    assert sent==[]
    assert client.post('/api/v1/land/analyze',json=body).status_code==200
    import json
    assert json.loads(sent[0].content)['input']=='1168011200101280003'
