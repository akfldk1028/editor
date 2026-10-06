"""backend.app.adapters.planm_agent: the one HTTP client of the Plan Agent."""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import httpx
import pytest

from backend.app.adapters.planm_agent import DEFAULT_URL, PlanmClient, run_planm_stage


def _agent(handler):
    return PlanmClient("http://plan.test", transport=httpx.MockTransport(handler))


def _request_body(request: httpx.Request) -> dict:
    return json.loads(request.content)


RESULT = {
    "contract_version": "skill-result/v1", "skill_name": "normalize-plan-request", "status": "success",
    "outputs": {"unresolved_facts": ["jurisdiction"]}, "violations": [], "artifacts": [],
    "provenance": {"started_at": "2026-10-05T12:00:00+00:00", "finished_at": "2026-10-05T12:00:01+00:00",
                   "attempt": 1, "input_sha256": "a" * 64, "output_sha256": "b" * 64}}


def _bundle(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _zip_reply(members: dict[str, bytes]) -> httpx.Response:
    return httpx.Response(200, content=_bundle(members), headers={"Content-Type": "application/zip"})


def _run(tmp_path: Path):
    run_root = tmp_path / "run"
    (run_root / "artifacts").mkdir(parents=True)
    (run_root / "input").mkdir()
    (run_root / "input" / "mass.json").write_text("{}", encoding="utf-8")
    (run_root / "artifacts" / "earlier.json").write_text('{"from": "analyze"}', encoding="utf-8")
    return run_root


def _stage(run_root: Path, handler, **overrides):
    kwargs = dict(stage="normalize", input_path=run_root / "input" / "mass.json",
                  state_path=run_root / "artifacts" / "planm-state.json",
                  output_dir=run_root / "artifacts", run_root=run_root, client=_agent(handler))
    kwargs.update(overrides)
    return run_planm_stage(**kwargs)


def test_the_run_directory_travels_with_the_request_and_outputs_come_back(tmp_path: Path) -> None:
    """planm-stage-bundle/v1: the agent is on another server and never sees this disk."""
    seen = []

    def handler(request):
        seen.append(request)
        return _zip_reply({"artifacts/planm-state.json": b'{"stage": "normalized"}',
                           "artifacts/alternatives/a1/plan.svg": b"<svg/>",
                           "skill-result.json": json.dumps(RESULT).encode()})
    run_root = _run(tmp_path)
    result = _stage(run_root, handler)
    assert result["status"] == "success"
    request = seen[0]
    assert request.url.path == "/planm/stage-bundle"
    assert dict(request.url.params) == {"stage": "normalize", "input": "input/mass.json",
                                        "state": "artifacts/planm-state.json", "output": "artifacts"}
    sent = zipfile.ZipFile(io.BytesIO(request.content)).namelist()
    assert sorted(sent) == ["artifacts/earlier.json", "input/mass.json"]   # relative names, no host paths
    assert (run_root / "artifacts" / "planm-state.json").read_text(encoding="utf-8") == '{"stage": "normalized"}'
    assert (run_root / "artifacts" / "alternatives" / "a1" / "plan.svg").read_bytes() == b"<svg/>"


def test_paths_outside_the_owned_run_root_never_reach_the_agent(tmp_path: Path) -> None:
    called = []
    run_root = _run(tmp_path)
    with pytest.raises(ValueError, match="run root"):
        _stage(run_root, lambda request: called.append(request) or httpx.Response(200),
               state_path=tmp_path / "escaped-state.json")
    assert not called


def test_a_bundle_that_writes_outside_the_output_folder_is_refused(tmp_path: Path) -> None:
    run_root = _run(tmp_path)
    reply = {"input/mass.json": b"replaced", "skill-result.json": json.dumps(RESULT).encode()}
    with pytest.raises(ValueError, match="outside the output folder"):
        _stage(run_root, lambda request: _zip_reply(reply))
    assert (run_root / "input" / "mass.json").read_text(encoding="utf-8") == "{}"


def test_a_reply_that_only_spoofs_the_version_is_rejected(tmp_path: Path) -> None:
    run_root = _run(tmp_path)
    reply = {"skill-result.json": json.dumps({"contract_version": "skill-result/v1"}).encode()}
    with pytest.raises(ValueError, match="skill-result.schema.json"):
        _stage(run_root, lambda request: _zip_reply(reply))


@pytest.mark.parametrize("handler, error, match", [
    (lambda request: (_ for _ in ()).throw(httpx.ConnectError("refused")), RuntimeError, "unreachable"),
    (lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("slow")), TimeoutError, "exceeded"),
    (lambda request: httpx.Response(500, json={"error": "boom"}), RuntimeError, "failed"),
    (lambda request: httpx.Response(200, content=b"not json"), ValueError, "without a bundle"),
    (lambda request: httpx.Response(422, json={"error": "unsupported stage"}), RuntimeError, "refused"),
])
def test_agent_failures_map_onto_the_run_services_retryable_errors(tmp_path, handler, error, match) -> None:
    with pytest.raises(error, match=match):
        _stage(_run(tmp_path), handler)


def test_the_agent_network_token_rides_every_call(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("A2A_TOKEN", "mesh-secret")
    seen = []

    def handler(request):
        seen.append(request.headers.get("authorization"))
        return _zip_reply({"skill-result.json": json.dumps(RESULT).encode()})
    _stage(_run(tmp_path), handler)
    assert seen == ["Bearer mesh-secret"]


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
