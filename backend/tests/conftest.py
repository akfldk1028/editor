"""Suite-wide defaults."""
import pytest


@pytest.fixture(autouse=True)
def _model_auth_is_api_key(monkeypatch):
    # A developer machine with the Claude CLI would otherwise route key-less model templates
    # through the real CLI (core.model_auth); tests that need oauth set it themselves.
    monkeypatch.setenv('EDITOR_MODEL_AUTH', 'api_key')
