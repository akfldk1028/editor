from __future__ import annotations

from pathlib import Path
import subprocess
import sys


bridge = Path(__file__).resolve().parents[3] / "adapters" / "planm_bridge.py"
raise SystemExit(
    subprocess.run(
        [sys.executable, str(bridge), "review", *sys.argv[1:]],
        shell=False,
        check=False,
    ).returncode
)
