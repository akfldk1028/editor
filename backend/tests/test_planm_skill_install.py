from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


INSTALLER_PATH = (
    Path(__file__).parents[2]
    / "agents"
    / "planm"
    / "install_codex_skills.py"
)


def _installer_module():
    spec = importlib.util.spec_from_file_location("planm_skill_installer", INSTALLER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_codex_copy_install_records_source_hashes(tmp_path: Path) -> None:
    module = _installer_module()

    manifest_path = module.install(codex_home=tmp_path, mode="copy")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["contract_version"] == "planm-skill-install/v1"
    assert len(manifest["skills"]) == 5
    installed = tmp_path / "skills" / "generate-plan-alternatives"
    assert installed.is_dir()
    assert not installed.is_symlink()
    assert (installed / "SKILL.md").is_file()
    assert len(manifest["skills"]["generate-plan-alternatives"]["sha256"]) == 64


def test_codex_link_install_keeps_planm_as_single_source(tmp_path: Path) -> None:
    module = _installer_module()

    module.install(codex_home=tmp_path, mode="link")

    installed = tmp_path / "skills" / "review-floorplan"
    assert installed.is_symlink()
    assert installed.resolve().name == "review-floorplan"


def test_install_refuses_to_replace_unmanaged_skill(tmp_path: Path) -> None:
    module = _installer_module()
    target = tmp_path / "skills" / "review-floorplan"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("unmanaged", encoding="utf-8")

    with pytest.raises(FileExistsError, match="unmanaged skill"):
        module.install(codex_home=tmp_path, mode="copy")
