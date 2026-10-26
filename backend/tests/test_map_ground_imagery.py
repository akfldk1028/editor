import asyncio
import io
import json
import time

import httpx
import pytest
from PIL import Image
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.modules.land import map_ground_imagery as m
from backend.app.modules.land.routers.map import create_land_map_router


def png(color=(20, 80, 40, 255)):
    output = io.BytesIO()
    Image.new('RGBA', (256, 256), color).save(output, format='PNG')
    return output.getvalue()


def test_style_bounds_and_invalid_png(tmp_path):
    client = m.GroundImagery(root=tmp_path)
    assert m.digest(client.style.encode()) == m.STYLE_SHA
    assert m.validate_png(m.EMPTY) is True
    assert m.validate_png(png()) is False
    for raw in (b'bad', png()[:-15], b'a'*(m.LIMIT+1)):
        with pytest.raises(m.ImageryUnavailable): m.validate_png(raw)
    async def run():
        for key in ((12, 3494, 1583), (18, 0, 0), (13, -1, 0)):
            with pytest.raises(ValueError): await client.get(*key)
        assert await client.get(13, 0, 0) == m.EMPTY
    asyncio.run(run())


def test_cache_hash_ttl_and_transparent_success(tmp_path):
    calls = []
    def fetch(request):
        calls.append(request)
        assert request.url.params['CRS'] == 'EPSG:3857'
        assert request.url.params['SLD_BODY'].encode() == m.GroundImagery(root=tmp_path).style.encode()
        return httpx.Response(200, content=m.EMPTY)
    client = m.GroundImagery(root=tmp_path, transport=httpx.MockTransport(fetch), interval=0)
    async def run():
        key = (13, 6988, 3166)
        assert await client.get(*key) == m.EMPTY
        assert await client.get(*key) == m.EMPTY
        assert len(calls) == 1
        file, receipt = client.paths(key)
        record = json.loads(receipt.read_bytes())
        assert record['alphaEmpty'] and record['styleSHA256'] == m.STYLE_SHA
        file.write_bytes(png())
        await client.get(*key)
        assert len(calls) == 2
        record = json.loads(receipt.read_bytes());record['at'] = time.time()-m.TTL-1
        receipt.write_text(json.dumps(record))
        await client.get(*key)
        assert len(calls) == 3
    asyncio.run(run())


def test_cancelled_consumer_keeps_coalesced_request_and_two_slots(tmp_path):
    async def run():
        calls=0;active=0;maximum=0
        started=asyncio.Event();release=asyncio.Event()
        async def fetch(request):
            nonlocal calls,active,maximum
            calls+=1;active+=1;maximum=max(maximum,active);started.set()
            await release.wait();active-=1
            return httpx.Response(200,content=png())
        client=m.GroundImagery(root=tmp_path,transport=httpx.MockTransport(fetch),interval=0)
        first=asyncio.create_task(client.get(13,6988,3166));await started.wait()
        second=asyncio.create_task(client.get(13,6988,3166))
        first.cancel()
        with pytest.raises(asyncio.CancelledError): await first
        others=[asyncio.create_task(client.get(13,6988+i,3166)) for i in (1,2,3)]
        await asyncio.sleep(.05);assert maximum==2
        release.set();assert await second==png()
        await asyncio.gather(*others)
        assert calls==4 and maximum==2 and not client.pending
    asyncio.run(run())


def test_error_body_hidden_response_bound_and_retry(tmp_path,monkeypatch):
    real_sleep=asyncio.sleep
    async def fast_sleep(seconds): await real_sleep(0)
    monkeypatch.setattr(m.asyncio,'sleep',fast_sleep)
    async def run():
        calls=[]
        def fetch(request):
            calls.append(1)
            return httpx.Response(503,headers={'Retry-After':'1'}) if len(calls)<3 else httpx.Response(200,content=png())
        client=m.GroundImagery(root=tmp_path/'retry',transport=httpx.MockTransport(fetch),interval=0)
        assert await client.get(13,6988,3166)==png() and len(calls)==3
        for response in (httpx.Response(200,content=b'a'*(m.LIMIT+1)),httpx.Response(403,text='SECRET https://private.invalid'),httpx.Response(200,text='<ServiceException/>')):
            bad=m.GroundImagery(root=tmp_path/'bad',transport=httpx.MockTransport(lambda r:response),interval=0)
            with pytest.raises(m.ImageryUnavailable,match='ground imagery|Ground imagery') as error:await bad.get(13,6988,3166)
            assert 'SECRET' not in str(error.value) and not list((tmp_path/'bad').glob('**/*.json'))
    asyncio.run(run())


def test_router_uses_png_cache_headers_and_generic_error(monkeypatch,tmp_path):
    monkeypatch.setenv('DATA_ROOT',str(tmp_path))
    async def get(self,z,x,y):
        if z==12:raise ValueError('bad')
        if x==7:raise m.ImageryUnavailable('private URL must never escape')
        return m.EMPTY
    monkeypatch.setattr(m.GroundImagery,'get',get)
    app=FastAPI();app.include_router(create_land_map_router());client=TestClient(app)
    good=client.get('/api/v1/land/ground-imagery/13/6988/3166.png')
    assert good.status_code==200 and good.content==m.EMPTY
    assert good.headers['cache-control']=='public, max-age=86400'
    assert client.get('/api/v1/land/ground-imagery/12/0/0.png').status_code==422
    bad=client.get('/api/v1/land/ground-imagery/13/7/0.png')
    assert bad.status_code==503 and bad.json()=={'detail':'Ground imagery unavailable'}
