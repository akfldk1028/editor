"""Three-column funnel compare across massv2 runs.

Usage:
    python tools/funnel_delta.py ovs3-full ovs5-delta ovs7-final

Reads runs/<name>/massv2-summary.json for each run and prints one row per
funnel stage plus the gate-reason tallies the Grand Repair targeted:
0 m2-yet-plausible holes, thin_element firings, and the storey histogram
of the plausible pool.
"""

from __future__ import annotations

from backend.app.modules.massing import paths as _mass_paths
from backend.app.modules.design.generation import paths as _design_paths
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime


import json
import math
import sys
from collections import Counter
from pathlib import Path

RUNS = _mass_paths.workspace_root() / "runs"


def load(name: str) -> dict:
    return json.loads((RUNS / name / "massv2-summary.json").read_text(encoding="utf-8"))


def reason_hits(records: list[dict], prefix: str) -> int:
    hits = 0
    for record in records:
        plausibility = record.get("plausibility") or {}
        if any(reason.startswith(prefix) for reason in plausibility.get("reasons", [])):
            hits += 1
    return hits


def storey_histogram(records: list[dict]) -> Counter:
    histogram: Counter = Counter()
    for record in records:
        plausibility = record.get("plausibility") or {}
        if record.get("status") != "compiled" or plausibility.get("reasons"):
            continue
        measurement = record.get("measurement") or {}
        height = measurement.get("height_m")
        floor = record.get("floor_height_m")
        if not height or not floor:
            continue
        histogram[max(1, math.floor(height / floor + 0.25))] += 1
    return histogram


def column(name: str) -> dict:
    summary = load(name)
    records = summary["records"]
    refused = summary["refused"]
    plausible = summary["compiled"] - summary["unlawful"] - summary["implausible"]
    gap_closed = refused.get("gap_closed", [])
    return {
        "forms": summary["form_count"],
        "compiled": summary["compiled"],
        "unlawful": summary["unlawful"],
        "implausible": summary["implausible"],
        "plausible": plausible,
        "delivered": summary["delivered"],
        "refused_silent": len(refused.get("silent", [])),
        "refused_clipped": len(refused.get("clipped_by_law", [])),
        "refused_gap": len(gap_closed),
        "zero_gfa_plausible": sum(
            1 for record in records
            if record.get("status") == "compiled"
            and not (record.get("plausibility") or {}).get("reasons")
            and (record.get("gfa_m2") or 0) <= 0
        ),
        "thin_element": reason_hits(records, "thin_element"),
        "below_min_plate": reason_hits(records, "delivers_"),
        "storeys": storey_histogram(records),
    }


def main() -> None:
    names = sys.argv[1:] or ["ovs3-full", "ovs5-delta", "ovs7-final"]
    columns = {name: column(name) for name in names}
    rows = [
        "forms", "compiled", "unlawful", "implausible", "plausible", "delivered",
        "refused_silent", "refused_clipped", "refused_gap",
        "zero_gfa_plausible", "thin_element", "below_min_plate",
    ]
    width = max(len(name) for name in names) + 2
    print("stage".ljust(18) + "".join(name.rjust(width) for name in names))
    for row in rows:
        print(row.ljust(18) + "".join(str(columns[name][row]).rjust(width) for name in names))
    print()
    storey_keys = sorted({k for col in columns.values() for k in col["storeys"]})
    print("plausible pool by storeys")
    for key in storey_keys:
        print(f"{key}F".ljust(18) + "".join(str(columns[name]["storeys"].get(key, 0)).rjust(width) for name in names))


if __name__ == "__main__":
    main()
