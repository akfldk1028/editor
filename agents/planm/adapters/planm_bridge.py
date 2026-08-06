from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
ENGINE = Path(
    os.environ.get(
        "PLANM_ENGINE_PATH",
        REPOSITORY_ROOT / "backend" / "app" / "adapters" / "planm_engine.py",
    )
)
STAGES = ("normalize", "analyze", "alternatives", "review", "deliver")
STAGE_SKILLS = {
    "normalize": "normalize-plan-request",
    "analyze": "analyze-building-mass",
    "alternatives": "generate-plan-alternatives",
    "review": "review-floorplan",
    "deliver": "deliver-planm-package",
}


def _timeout_result(stage: str, request: dict, timeout_seconds: float) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    input_hash = hashlib.sha256(
        json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    output_hash = hashlib.sha256(b"{}").hexdigest()
    return {
        "contract_version": "skill-result/v1",
        "skill_name": STAGE_SKILLS[stage],
        "status": "blocked",
        "outputs": {},
        "violations": [
            {
                "code": "engine_timeout",
                "message": f"PLANM engine exceeded {timeout_seconds:g} seconds",
                "severity": "hard",
                "retryable": True,
            }
        ],
        "artifacts": [],
        "provenance": {
            "started_at": now,
            "finished_at": now,
            "attempt": 1,
            "input_sha256": input_hash,
            "output_sha256": output_hash,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="planm-agent-bridge")
    parser.add_argument("stage", choices=STAGES)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    request = {
        "contract_version": "planm-stage-request/v1",
        "stage": args.stage,
        "input_path": str(args.input),
        "state_path": str(args.state),
        "output_dir": str(args.output_dir),
    }
    timeout_seconds = float(os.environ.get("PLANM_ENGINE_TIMEOUT_SECONDS", "290"))
    try:
        completed = subprocess.run(
            [sys.executable, str(ENGINE)],
            cwd=REPOSITORY_ROOT,
            input=json.dumps(request, ensure_ascii=False),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        print(json.dumps(_timeout_result(args.stage, request, timeout_seconds)))
        return 4
    if completed.stdout:
        sys.stdout.write(completed.stdout)
    if completed.stderr:
        sys.stderr.write(completed.stderr)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
