"""localhost and 127.0.0.1 on the same port are the editor's own page; other origins still are not."""
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from backend.app.core.loopback_origin import LoopbackOrigin, alias_of

PUBLIC = 'http://127.0.0.1:3003'


def app():
    application = FastAPI()

    @application.post('/w')
    async def write(request: Request):
        if request.headers.get('origin') not in (None, PUBLIC):
            raise HTTPException(403)
        return {'ok': True}
    application.add_middleware(LoopbackOrigin, public=PUBLIC)
    return TestClient(application)


def test_a_loopback_alias_of_the_public_origin_is_the_same_page():
    client = app()
    assert client.post('/w', headers={'Origin': 'http://localhost:3003'}).status_code == 200
    assert client.post('/w', headers={'Origin': PUBLIC}).status_code == 200


def test_other_origins_are_still_refused():
    client = app()
    for origin in ('http://localhost:3005', 'https://localhost:3003', 'http://evil.example:3003'):
        assert client.post('/w', headers={'Origin': origin}).status_code == 403
    assert not alias_of('http://localhost', 'http://127.0.0.1')
