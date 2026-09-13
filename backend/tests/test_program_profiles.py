"""Use profiles are data: one JSON file per use type, every number with its evidence."""

import json
from pathlib import Path

import pytest

from backend.app.modules.program_prior.service import (
    COMMERCIAL_PROFILE,
    OFFICE_PROFILE,
    ProgramProfile,
    load_profile,
)
from backend.app.modules.program_prior.sizing import OFFICE_SIZING, load_sizing_rules

PROFILE_DIR = Path(__file__).resolve().parents[1] / "app" / "modules" / "program_prior" / "profiles"


@pytest.mark.parametrize("path", sorted(PROFILE_DIR.glob("*.json")), ids=lambda p: p.stem)
def test_every_profile_file_loads_and_names_its_use_type(path):
    data = json.loads(path.read_text(encoding="utf-8"))

    assert data["use_type"] == path.stem
    profile = load_profile(path.stem)
    assert isinstance(profile, ProgramProfile)
    space_types = {space.space_type for space in profile.spaces}
    assert "core" in space_types
    for relation in profile.relationships:
        assert relation.source in space_types or relation.source == "street"
        assert relation.target in space_types or relation.target == "street"


@pytest.mark.parametrize("path", sorted(PROFILE_DIR.glob("*.json")), ids=lambda p: p.stem)
def test_every_sizing_rule_carries_a_citation_and_an_evidence_level(path):
    rules = load_sizing_rules(path.stem) or {}
    for name, rule in rules.items():
        assert rule.citation.strip(), name
        assert rule.evidence_level in {"statutory", "practice", "assumed"}, name
        assert rule.basis in {"fixture", "occupancy", "fixed", "ratio", "residual"}, name


def test_the_module_constants_are_the_loaded_files():
    assert OFFICE_PROFILE == load_profile("office")
    assert COMMERCIAL_PROFILE == load_profile("neighborhood_commercial")
    assert OFFICE_SIZING == load_sizing_rules("office")
    assert OFFICE_PROFILE.sizing_rules == OFFICE_SIZING


def test_an_unknown_use_type_is_rejected():
    with pytest.raises(ValueError, match="unsupported use_type"):
        load_profile("spaceport")
