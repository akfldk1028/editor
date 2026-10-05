"""The PLANM contracts this product validates against, and their parity with the Plan Agent's copies."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from backend.app.core.json_contracts import CONTRACT_ROOT, validate_planm_contract

PLAN_ROOT = Path(__file__).parents[2]
AGENT_CONTRACTS = PLAN_ROOT.parent / "agents" / "planm" / "contracts"
SCHEMAS = ("planm-stage-request.schema.json", "planm-state.schema.json", "skill-result.schema.json")


def _request() -> dict:
    return {
        "contract_version": "planm-stage-request/v1",
        "stage": "normalize",
        "input_path": "input/mass.json",
        "state_path": "artifacts/planm-state.json",
        "output_dir": "artifacts",
    }


def test_runtime_validator_enforces_the_checked_in_request_schema() -> None:
    validate_planm_contract("planm-stage-request.schema.json", _request())
    with pytest.raises(ValueError, match="planm-stage-request.schema.json"):
        validate_planm_contract("planm-stage-request.schema.json", {**_request(), "unexpected": True})


def test_schema_names_cannot_escape_the_contract_root() -> None:
    with pytest.raises(ValueError, match="invalid"):
        validate_planm_contract("../other.schema.json", {})
    with pytest.raises(ValueError, match="missing"):
        validate_planm_contract("nothing.schema.json", {})


@pytest.mark.parametrize("name", SCHEMAS)
def test_vendored_schema_matches_the_plan_agents_copy(name: str) -> None:
    """The Plan Agent owns the contracts; this product keeps byte copies and must not drift."""
    theirs = AGENT_CONTRACTS / name
    if not theirs.is_file():
        pytest.skip("agents/planm is not checked out beside this product")
    assert hashlib.sha256((CONTRACT_ROOT / name).read_bytes()).hexdigest() == \
        hashlib.sha256(theirs.read_bytes()).hexdigest(), f"{name} drifted from agents/planm/contracts; copy it again"
