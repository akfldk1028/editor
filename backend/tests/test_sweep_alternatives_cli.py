import subprocess
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPOSITORY_ROOT / "resources" / "scripts" / "sweep_alternatives.py"


def test_sweep_help_prints_usage_without_creating_outputs(tmp_path: Path) -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--help", "--summarize-only"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    assert completed.returncode == 0
    assert "usage:" in completed.stdout.lower()
    assert list(tmp_path.iterdir()) == []


def test_sweep_rejects_unknown_options_without_creating_outputs(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--not-a-real-option",
            "--summarize-only",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    assert completed.returncode == 2
    assert "unrecognized arguments" in completed.stderr.lower()
    assert list(tmp_path.iterdir()) == []
