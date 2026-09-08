from __future__ import annotations

from pathlib import Path
import subprocess
import sys


bridge = Path(__file__).resolve().parents[3] / "runtime" / "planm_bridge.py"
raise SystemExit(
    subprocess.run(
        [sys.executable, str(bridge), "normalize", *sys.argv[1:]],
        shell=False,
        check=False,
    ).returncode
)
