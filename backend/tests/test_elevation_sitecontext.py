"""provider=sitecontext_ngii: heights come from the Site Context Agent over HTTP, strictly."""
import json

import httpx
import pytest

from backend.app.adapters.elevation import ElevationClient, ElevationFetchError


def site(reply):
    seen = []

    def respond(request):
        body = json.loads(request.content)
        seen.append((request.url.path, body))
        return httpx.Response(200, json=reply(body['points']))
    return httpx.MockTransport(respond), seen


def test_heights_come_from_site_in_order_with_provenance():
    transport, seen = site(lambda pts: {'status': 'ok', 'source': 'sitecontext_ngii',
                                        'heights': [50.0 + i for i in range(len(pts))],
                                        'dataset': {'vrt_sha256': 'a' * 64}})
    client = ElevationClient('sitecontext_ngii', transport=transport)
    assert client.fetch([(37.5, 127.0), (37.6, 127.1)]) == [50.0, 51.0]
    assert seen[0][0] == '/site/ground-heights' and seen[0][1]['points'] == [[37.5, 127.0], [37.6, 127.1]]
    assert client.provenance['actual_provider'] == 'sitecontext_ngii'
    assert client.provenance['fallback_used'] is False


@pytest.mark.parametrize('reply', [
    lambda pts: {'status': 'needs_evidence', 'reason': 'no NGII contour near the parcel'},
    lambda pts: {'status': 'ok', 'source': 'open_meteo', 'heights': [1.0] * len(pts)},
    lambda pts: {'status': 'ok', 'source': 'sitecontext_ngii', 'heights': [1.0]},
])
def test_no_answer_or_a_foreign_answer_is_refused_never_replaced(reply):
    transport, _ = site(reply)
    with pytest.raises(ElevationFetchError):
        ElevationClient('sitecontext_ngii', transport=transport).fetch([(37.5, 127.0), (37.6, 127.1)])


def test_reference_engine_asks_site_too(monkeypatch):
    from backend.app.modules.land.reference import config
    from backend.app.modules.land.reference.services.datum import elevation_api
    from backend.app.adapters import site_context
    monkeypatch.setattr(config, 'ELEVATION_PROVIDER', 'sitecontext_ngii')
    monkeypatch.setattr(site_context, 'ground_heights', lambda pts: ([7.0] * len(pts), {}))
    assert elevation_api.fetch_elevations([(37.5, 127.0)]) == [7.0]

    def refuse(pts):
        raise site_context.SiteHeightsError('down')
    monkeypatch.setattr(site_context, 'ground_heights', refuse)
    with pytest.raises(elevation_api.ElevationFetchError):
        elevation_api.fetch_elevations([(37.5, 127.0)])
