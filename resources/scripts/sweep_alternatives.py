"""Map the input envelope of the alternatives review.

Runs the deterministic alternatives review across a matrix of footprints, floor
counts, and use mixes, then reports which combinations fail to reach the two
accepted alternatives the product requires before approval.

Usage: python resources/scripts/sweep_alternatives.py [output_root]
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

FOOTPRINTS = {
    "20x10": [[0, 0], [20, 0], [20, 10], [0, 10]],
    "30x12": [[0, 0], [30, 0], [30, 12], [0, 12]],
    "40x24": [[0, 0], [40, 0], [40, 24], [0, 24]],
    "24x24": [[0, 0], [24, 0], [24, 24], [0, 24]],
    "60x20": [[0, 0], [60, 0], [60, 20], [0, 20]],
    "L-shape": [[0, 0], [36, 0], [36, 14], [18, 14], [18, 26], [0, 26]],
}
FLOOR_COUNTS = (1, 3, 5, 8)
COMMERCIAL_SHARES = (0.0, 0.2, 0.34, 1.0)


def case_name(footprint: str, floors: int, share: float) -> str:
    return f"{footprint}-f{floors}-c{int(share * 100):03d}"


def build_mass(name: str, footprint: str, floors: int, share: float) -> dict:
    return {
        "project_id": name,
        "floors": floors,
        "footprint_polygon": FOOTPRINTS[footprint],
        "site_edges": [{"edge_index": 0, "kind": "street"}],
        "access_candidates": [{"edge_index": 0, "position": 0.5}],
        "use_mix": {
            "neighborhood_commercial": share,
            "office": round(1.0 - share, 4),
        },
    }


def run_case(mass: dict, output_dir: Path) -> dict:
    with tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8"
    ) as handle:
        json.dump(mass, handle)
        input_path = Path(handle.name)
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "backend.app.cli",
                "alternatives-review",
                "--input",
                str(input_path),
                "--output-dir",
                str(output_dir),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    finally:
        input_path.unlink(missing_ok=True)

    # The CLI exits non-zero whenever a run falls short of two accepted
    # alternatives, so the report is the authority on what happened. Only a
    # missing report is an execution error.
    report_path = output_dir / "alternatives.review.json"
    if not report_path.is_file():
        detail = (completed.stderr or completed.stdout or "").strip().splitlines()
        return {
            "accepted_count": 0,
            "outcome": "error",
            "detail": detail[-1] if detail else f"exit {completed.returncode}",
        }

    return summarize_report(report_path)


def summarize_report(report_path: Path) -> dict:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    rejected = []
    for alternative in report["alternatives"]:
        if alternative["accepted"]:
            continue
        reasons = [
            stage
            for stage in ("internal_validation", "render_validation")
            if alternative[stage]["status"] != "pass"
        ]
        rejected.append(f"{alternative['alternative_id']}:{'+'.join(reasons) or 'other'}")

    accepted_count = report["accepted_count"]
    return {
        "accepted_count": accepted_count,
        "outcome": "ok" if accepted_count >= 2 else "insufficient",
        "detail": ", ".join(rejected),
    }


def main() -> int:
    arguments = [value for value in sys.argv[1:] if value != "--summarize-only"]
    summarize_only = "--summarize-only" in sys.argv
    output_root = Path(arguments[0] if arguments else "logs/runs/sweep")
    output_root.mkdir(parents=True, exist_ok=True)
    results = []
    for footprint in FOOTPRINTS:
        for floors in FLOOR_COUNTS:
            for share in COMMERCIAL_SHARES:
                name = case_name(footprint, floors, share)
                case_dir = output_root / name
                report_path = case_dir / "alternatives.review.json"
                if summarize_only:
                    if not report_path.is_file():
                        continue
                    result = summarize_report(report_path)
                else:
                    result = run_case(
                        build_mass(name, footprint, floors, share),
                        case_dir,
                    )
                results.append({"case": name, **result})
                print(
                    f"{name:22} {result['outcome']:12} "
                    f"accepted={result['accepted_count']} {result['detail']}",
                    flush=True,
                )

    summary_path = output_root / "sweep-summary.json"
    summary_path.write_text(
        json.dumps({"results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    failing = [item for item in results if item["outcome"] != "ok"]
    print(f"\n{len(results) - len(failing)}/{len(results)} cases reached two accepted")
    for item in failing:
        print(f"  FAIL {item['case']:22} {item['outcome']:12} {item['detail']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
