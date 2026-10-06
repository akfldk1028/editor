"""The layer contract in pyproject.toml ([tool.importlinter]) holds: higher layers import lower ones only."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_app_layers_contract_is_kept(monkeypatch):
    cli = pytest.importorskip('importlinter.cli', reason='import-linter is a dev dependency (pip install -e .[dev])')
    monkeypatch.chdir(ROOT)
    assert cli.lint_imports(config_filename=str(ROOT / 'pyproject.toml')) == 0, 'run `lint-imports` from the editor root'
