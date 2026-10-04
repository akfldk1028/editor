from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from backend.app.core.planm_location import planm_agent_dir


def test_default_owner_remains_sibling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv('PLANM_AGENT_DIR', raising=False)
    assert planm_agent_dir(tmp_path / 'editor') == tmp_path / 'agents' / 'planm'


@pytest.mark.parametrize('value', ['relative/planm', '', '   '])
def test_explicit_owner_must_be_absolute(value: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('PLANM_AGENT_DIR', value)
    with pytest.raises(ValueError, match='PLANM_AGENT_DIR.*absolute'):
        planm_agent_dir(tmp_path / 'editor')


def test_override_shared_by_config_schema_and_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.app.adapters.planm_agent import build_planm_host_command
    from backend.app.core.json_contracts import validate_planm_contract
    from backend.app.modules.planm_runs.service import _maximum_stage_attempts

    owner = tmp_path / 'external owner'
    (owner / 'config').mkdir(parents=True)
    (owner / 'contracts').mkdir()
    (owner / 'config/default.yaml').write_text('planm:\n  maximum_stage_attempts: 4\n')
    (owner / 'contracts/probe.schema.json').write_text(json.dumps({'const': {'owner': 'external'}}))
    monkeypatch.setenv('PLANM_AGENT_DIR', str(owner))
    monkeypatch.setattr('backend.app.adapters.planm_agent.shutil.which', lambda _: 'node')
    product = tmp_path / 'relocated editor'
    assert planm_agent_dir(product) == owner
    assert _maximum_stage_attempts(product) == 4
    validate_planm_contract(product, 'probe.schema.json', {'owner': 'external'})
    with pytest.raises(ValueError, match='contract validation failed'):
        validate_planm_contract(product, 'probe.schema.json', {'owner': 'wrong'})
    assert build_planm_host_command(product)[1] == str(owner / 'runtime/gitagent_host.mjs')


@pytest.mark.parametrize('platform,expected', [('nt', 0x08000000), ('posix', 0)])
def test_stage_launch_hides_windows_and_preserves_owner_environment(
    platform: str, expected: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.adapters import planm_agent as adapter

    owner = tmp_path / 'external owner'
    monkeypatch.setenv('PLANM_AGENT_DIR', str(owner))
    monkeypatch.setattr(adapter, 'os', SimpleNamespace(name=platform, environ=os.environ.copy()))
    monkeypatch.setattr(adapter.shutil, 'which', lambda _: 'node')
    monkeypatch.setattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000, raising=False)
    captured = {}

    def launch(command, **kwargs):
        captured.update(kwargs)
        captured['command'] = command
        raise subprocess.TimeoutExpired(command, kwargs['timeout'])

    monkeypatch.setattr(adapter.subprocess, 'run', launch)
    with pytest.raises(TimeoutError, match='PLANM agent'):
        adapter.run_planm_stage(stage='normalize', input_path=tmp_path / 'input.json',
            state_path=tmp_path / 'state.json', output_dir=tmp_path / 'output',
            repository_root=tmp_path / 'editor', run_root=tmp_path)
    assert captured['creationflags'] == expected
    assert captured['env']['PLANM_AGENT_DIR'] == str(owner)
    assert captured['command'][1] == str(owner / 'runtime/gitagent_host.mjs')
    assert captured['env']['PLANM_GITAGENT_RUNTIME_ENTRY'] == str(
        tmp_path / 'editor/infra/runtimes/gitagent/dist/exports.js')
