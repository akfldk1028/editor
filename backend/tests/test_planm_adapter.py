"""backend.app.adapters.planm_agent: the one HTTP client of the Plan Agent."""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from backend.app.adapters.planm_agent import DEFAULT_URL, PlanmClient, run_planm_stage


def _agent(handler):
    return PlanmClient("http://plan.test", transport=httpx.MockTransport(handler))


def _request_body(request: httpx.Request) -> dict:
    return json.loads(request.content)


def test_stage_request_is_the_versioned_contract_and_the_reply_is_validated(tmp_path: Path) -> None:
    seen = []

    def handler(request):
        seen.append((request.url.path, _request_body(request)))
        return httpx.Response(200, json={
            "contract_version": "skill-result/v1", "skill_name": "normalize-plan-request", "status": "success",
            "outputs": {"unresolved_facts": ["jurisdiction"]}, "violations": [], "artifacts": [],
            "provenance": {"started_at": "2026-10-05T12:00:00+00:00", "finished_at": "2026-10-05T12:00:01+00:00",
                           "attempt": 1, "input_sha256": "a" * 64, "output_sha256": "b" * 64}})
    run_root = tmp_path / "run"
    (run_root / "artifacts").mkdir(parents=True)
    (run_root / "mass.json").write_text("{}", encoding="utf-8")
    result = run_planm_stage(stage="normalize", input_path=run_root / "mass.json",
                             state_path=run_root / "artifacts" / "planm-state.json",
                             output_dir=run_root / "artifacts", run_root=run_root, client=_agent(handler))
    assert result["status"] == "success"
    path, body = seen[0]
    assert path == "/planm/stage"
    assert body["contract_version"] == "planm-stage-request/v1" and body["stage"] == "normalize"
    assert Path(body["input_path"]).is_absolute()


def test_paths_outside_the_owned_run_root_never_reach_the_agent(tmp_path: Path) -> None:
    called = []
    run_root = tmp_path / "run"
    run_root.mkdir()
    (run_root / "mass.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="run root"):
        run_planm_stage(stage="normalize", input_path=run_root / "mass.json",
                        state_path=tmp_path / "escaped-state.json", output_dir=run_root / "out",
                        run_root=run_root, client=_agent(lambda request: called.append(request) or httpx.Response(200, json={})))
    assert not called


def test_a_reply_that_only_spoofs_the_version_is_rejected(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    run_root.mkdir()
    (run_root / "mass.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="skill-result.schema.json"):
        run_planm_stage(stage="normalize", input_path=run_root / "mass.json", state_path=run_root / "s.json",
                        output_dir=run_root / "out", run_root=run_root,
                        client=_agent(lambda request: httpx.Response(200, json={"contract_version": "skill-result/v1"})))


@pytest.mark.parametrize("handler, error, match", [
    (lambda request: (_ for _ in ()).throw(httpx.ConnectError("refused")), RuntimeError, "unreachable"),
    (lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("slow")), TimeoutError, "exceeded"),
    (lambda request: httpx.Response(500, json={"error": "boom"}), RuntimeError, "failed"),
    (lambda request: httpx.Response(200, content=b"not json"), ValueError, "without JSON"),
    (lambda request: httpx.Response(422, json={"error": "outside the configured stage roots"}), RuntimeError, "refused"),
])
def test_agent_failures_map_onto_the_run_services_retryable_errors(tmp_path, handler, error, match) -> None:
    run_root = tmp_path / "run"
    run_root.mkdir()
    (run_root / "mass.json").write_text("{}", encoding="utf-8")
    with pytest.raises(error, match=match):
        run_planm_stage(stage="normalize", input_path=run_root / "mass.json", state_path=run_root / "s.json",
                        output_dir=run_root / "out", run_root=run_root, client=_agent(handler))


def test_generate_forwards_the_body_and_returns_the_agents_document() -> None:
    def handler(request):
        assert request.url.path == "/planm/generate"
        body = _request_body(request)
        return httpx.Response(200, json={"algorithm": body["algorithm"], "num_results": 1, "results": [],
                                         "received_request_hash": "h", "design_acceptance": {"status": "not_verified"}})
    result = _agent(handler).generate({"algorithm": "subdivision", "rooms": [], "footprint_geojson": {}})
    assert result["algorithm"] == "subdivision" and result["design_acceptance"]["status"] == "not_verified"


def test_url_comes_from_the_environment_or_the_default(monkeypatch) -> None:
    monkeypatch.delenv("PLANM_AGENT_URL", raising=False)
    assert PlanmClient().base_url == DEFAULT_URL
    monkeypatch.setenv("PLANM_AGENT_URL", "http://10.0.0.5:8308/")
    assert PlanmClient().base_url == "http://10.0.0.5:8308"
