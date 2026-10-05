"""The absorbed design law paths share Editor's bounded provider contract."""
import asyncio
import json
from pathlib import Path
import runpy
from types import SimpleNamespace

import httpx
import pytest

from backend.app.adapters.law_search import LawSearchClient
from backend.app.modules.land.reference import config
from backend.app.modules.land.reference.services import law_enricher


def provider(monkeypatch, primary, fallback=None):
    monkeypatch.setattr(config, "LAW_BACKEND_URL", "https://configured-law.invalid")
    monkeypatch.setattr(config, "AG_LIGHT_URL", "https://configured-fallback.invalid" if fallback else "")
    monkeypatch.setattr(law_enricher, "LawSearchClient", lambda *args, **kwargs: LawSearchClient(
        *args, **kwargs, transport=httpx.MockTransport(primary),
        fallback_transport=httpx.MockTransport(fallback) if fallback else None))


def test_reference_configuration_has_no_implicit_law_endpoints(monkeypatch):
    monkeypatch.delenv("LAW_BACKEND_URL", raising=False)
    monkeypatch.delenv("AG_LIGHT_URL", raising=False)
    snapshot = runpy.run_path(str(Path(config.__file__)))
    try:
        assert snapshot["LAW_BACKEND_URL"] == snapshot["AG_LIGHT_URL"] == ""
        assert "law_client" not in snapshot and "light_client" not in snapshot
    finally:
        snapshot["_cleanup_clients"]()


def test_unconfigured_search_returns_errors_without_network(monkeypatch):
    monkeypatch.setattr(config, "LAW_BACKEND_URL", "")
    monkeypatch.setattr(config, "AG_LIGHT_URL", "")
    async def forbidden(*args, **kwargs):
        pytest.fail("Unconfigured law search attempted a network request")
    monkeypatch.setattr(LawSearchClient, "_post", forbidden)
    result = law_enricher.search_for_zones(["zone"])
    assert result == {"articles": [], "total_count": 0, "errors": ["Law search is not configured"]}


@pytest.mark.parametrize("failure", ["connect", "read", "status"])
def test_reference_search_uses_connection_only_fallback(monkeypatch, failure):
    calls = []
    async def primary(request):
        if failure == "connect":
            raise httpx.ConnectError("private transport information")
        if failure == "read":
            raise httpx.ReadTimeout("private transport information")
        return httpx.Response(503)
    async def fallback(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"results": [{"id": "law-1", "content": "citation", "score": .8}]})
    provider(monkeypatch, primary, fallback)
    result = law_enricher._parallel_search(["query"], 3)
    assert bool(calls) == (failure == "connect")
    if calls:
        assert result["total_count"] == 1
        assert result["articles"][0]["results"][0]["hang_id"] == "law-1"
        assert calls[0]["mode"] == "hybrid"
    else:
        assert result["errors"] and result["total_count"] == 0
    assert "private" not in json.dumps(result)


def test_reference_deadline_cancels_remaining_provider_requests(monkeypatch):
    active = peak = cancelled = 0
    async def primary(request):
        nonlocal active, peak, cancelled
        active += 1
        peak = max(peak, active)
        try:
            if json.loads(request.content)["query"] != "fast":
                await asyncio.sleep(10)
            return httpx.Response(200, json={"results": [{"content": "kept"}]})
        except asyncio.CancelledError:
            cancelled += 1
            raise
        finally:
            active -= 1
    provider(monkeypatch, primary)
    result = law_enricher._parallel_search(["fast"] + [str(i) for i in range(20)], 3, timeout=.05)
    assert result["total_count"] == 1 and result["errors"]
    assert active == 0 and peak <= 5 and cancelled > 0


def test_extraction_retains_unfiltered_deduplicated_citation_text(monkeypatch):
    async def primary(request):
        return httpx.Response(200, json={"results": [{
            "hang_id": "same", "content": "original citation", "similarity": .1,
            "law_name": "source law", "jo_name": "Article 7"}]})
    provider(monkeypatch, primary)
    assert law_enricher._fetch_article_texts(["first", "second"], []) == ["[source law Article 7]\noriginal citation"]
    assert law_enricher._parallel_search(["first"], 3)["total_count"] == 0


def test_structured_extraction_and_success_cache_are_preserved(monkeypatch):
    async def primary(request):
        return httpx.Response(200, json={"results": [{
            "content": "source citation", "law_name": "Source", "jo_name": "Article", "hang_id": "one"}]})
    provider(monkeypatch, primary)
    monkeypatch.setattr(config, "LLM_EXTRACTION_ENABLED", True)
    monkeypatch.setattr(config, "OPENAI_API_KEY", "test-only")
    requests = []
    def completion(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"bcr_pct":60,"far_pct":200}'))])
    monkeypatch.setattr(law_enricher, "_get_openai_client", lambda: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=completion))))
    law_enricher.clear_extraction_cache()
    try:
        first = law_enricher.extract_regulation_values(["zone"], "bcr_far")
        second = law_enricher.extract_regulation_values(["zone"], "bcr_far")
        assert first == second == {"bcr_pct": 60, "far_pct": 200}
        assert len(requests) == 1
        assert requests[0]["response_format"] == {"type": "json_object"}
        assert "source citation" in requests[0]["messages"][1]["content"]
    finally:
        law_enricher.clear_extraction_cache()


def test_law_agent_reports_unconfigured_without_claiming_attempt(monkeypatch):
    from backend.app.modules.design.generation.maas.agents.law_graph_agent.evidence import _bounded_law_domain_search
    monkeypatch.setattr(config, "LAW_BACKEND_URL", "")
    monkeypatch.setattr(config, "AG_LIGHT_URL", "")
    result = _bounded_law_domain_search("query", 3)
    assert result["attempted"] is False and result["available"] is False
    assert result["error_category"] == "law_service_not_configured"
    assert result["source"] == "editor-law-search"


def test_law_agent_uses_configured_fallback_and_preserves_evidence(monkeypatch):
    from backend.app.modules.design.generation.maas.agents.law_graph_agent.evidence import _bounded_law_domain_search
    async def primary(request):
        raise httpx.ConnectError("unreachable")
    async def fallback(request):
        assert json.loads(request.content)["limit"] == 3
        return httpx.Response(200, json={"results": [{"id": "evidence", "content": "text", "score": .1}]})
    provider(monkeypatch, primary, fallback)
    result = _bounded_law_domain_search("query", 50)
    assert result["attempted"] is True and result["available"] is True
    assert result["results"][0]["hang_id"] == "evidence"
    assert result["results"][0]["source"] == "ag-light"
