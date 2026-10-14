"""Suite-wide defaults."""
import pytest


@pytest.fixture(autouse=True)
def _model_auth_is_api_key(monkeypatch):
    # A developer machine with the Claude CLI would otherwise route key-less model templates
    # through the real CLI (core.model_auth); tests that need oauth set it themselves.
    monkeypatch.setenv('EDITOR_MODEL_AUTH', 'api_key')
    # The developer's own routing policy (EDITOR_ROUTING_JUDGE=auto|rules) must not change what a test routes.
    monkeypatch.delenv('EDITOR_ROUTING_JUDGE', raising=False)


@pytest.fixture(autouse=True)
def _ledger_in_tmp(monkeypatch, tmp_path_factory):
    # The 협업 장부 defaults to runtime/ledger; a test suite must never write there.
    monkeypatch.setenv('EDITOR_LEDGER_DIR', str(tmp_path_factory.mktemp('ledger')))
