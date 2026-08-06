from __future__ import annotations

import hashlib
import json
from pathlib import Path


PLAN_ROOT = Path(__file__).parents[2]
SAMPLE = PLAN_ROOT / "datasets" / "manifests" / "sample_mass_office_commercial.json"


def _run(stage: str, input_path: Path, state: Path, output_dir: Path) -> dict:
    from backend.app.adapters.planm_agent import run_planm_stage

    result = run_planm_stage(
        stage=stage,
        input_path=input_path,
        state_path=state,
        output_dir=output_dir,
        repository_root=PLAN_ROOT,
        run_root=output_dir.parent,
        timeout_seconds=120,
    )
    assert result["status"] == "success"
    return result


def test_planm_agent_delivers_distinct_reviewed_alternatives(tmp_path: Path) -> None:
    output_dir = tmp_path / "delivery"
    state = output_dir / "planm-state.json"
    input_path = tmp_path / "mass.json"
    input_path.write_bytes(SAMPLE.read_bytes())

    for stage in ("normalize", "analyze", "alternatives", "review", "deliver"):
        _run(stage, input_path, state, output_dir)

    manifest = json.loads((output_dir / "planm-manifest.json").read_text(encoding="utf-8"))
    assert manifest["contract_version"] == "planm-delivery/v1"
    assert len(manifest["accepted_alternative_ids"]) >= 2
    assert manifest["internal_validation"] == "pass"
    assert manifest["render_validation"] == "pass"
    assert manifest["regulatory_screening"] in {"pass", "not_checked"}
    assert len(set(manifest["preview_sha256"].values())) >= 2

    for artifact in manifest["artifacts"]:
        path = Path(artifact["path"])
        assert not path.is_absolute()
        path = output_dir / path
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == artifact["sha256"]

    final_state = json.loads(state.read_text(encoding="utf-8"))
    assert final_state["stage"] == "delivered"
