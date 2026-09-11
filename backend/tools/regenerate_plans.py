"""Regenerate the sample floor plans into a dated run folder.

Every run lands in its own directory under C:/DK/Editor/plans so successive
attempts can be compared side by side instead of overwriting each other.

    python -m backend.tools.regenerate_plans [--label before-residual-fix]
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path

from backend.app.modules.generation_loop.service import run_building_alternatives
from backend.app.modules.visual_review.service import (
    create_building_visual_review_artifacts,
)
from backend.app.schemas.mass import FloorFootprint, MassInput


DEFAULT_MANIFEST = (
    Path(__file__).resolve().parents[2]
    / "resources"
    / "datasets"
    / "manifests"
    / "sample_mass_irregular_12v_setback_office.json"
)
PLAN_ROOT = Path("C:/DK/Editor/plans")


def load_mass(manifest_path: Path) -> MassInput:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return MassInput(
        project_id=manifest["project_id"],
        floors=manifest["floors"],
        footprint_polygon=manifest["footprint_polygon"],
        floor_footprints=tuple(
            FloorFootprint(
                floor_index=floor["floor_index"],
                footprint_polygon=tuple(
                    (float(x), float(y)) for x, y in floor["footprint_polygon"]
                ),
            )
            for floor in manifest["floor_footprints"]
        ),
        site_edges=manifest["site_edges"],
        access_candidates=manifest["access_candidates"],
        use_mix=manifest["use_mix"],
    )


def regenerate(manifest_path: Path, label: str | None) -> Path:
    mass = load_mass(manifest_path)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = PLAN_ROOT / (f"{stamp}-{label}" if label else stamp)
    run_dir.mkdir(parents=True, exist_ok=True)

    result = run_building_alternatives(mass)
    report: dict = {
        "manifest": str(manifest_path),
        "generated_at": stamp,
        "label": label,
        "alternatives": [],
    }
    for alternative in result.alternatives:
        out = run_dir / alternative.alternative_id
        create_building_visual_review_artifacts(
            alternative.building,
            boundary=list(mass.footprint_polygon),
            output_dir=out,
            render_style="architectural",
        )
        floors = []
        for index, floor in enumerate(alternative.building.floor_results, start=1):
            relaxations = getattr(floor.program, "form_relaxations", ())
            floors.append(
                {
                    "floor_index": index,
                    "rooms": [
                        {
                            "room_id": node.node_id,
                            "target_area_m2": float(node.target_area),
                            "min_width_m": node.min_width,
                            "max_aspect_ratio": node.max_aspect_ratio,
                        }
                        for node in floor.program.nodes
                    ],
                    "area_deviations": [
                        {
                            "room_id": item.node_id,
                            "requested_m2": round(item.requested, 2),
                            "assigned_m2": round(item.assigned, 2),
                            "shortfall_pct": round(item.shortfall_ratio * 100, 1),
                            "reason": item.reason,
                        }
                        for item in getattr(floor.program, "area_deviations", ())
                    ],
                    "form_relaxations": [
                        {
                            "room_id": item.node_id,
                            "field": item.field,
                            "required": item.required,
                            "relaxed_to": item.relaxed_to,
                            "reason": item.reason,
                        }
                        for item in relaxations
                    ],
                }
            )
        report["alternatives"].append(
            {
                "alternative_id": alternative.alternative_id,
                "accepted": bool(alternative.accepted),
                "floors": floors,
            }
        )

    (run_dir / "report.json").write_text(
        json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    return run_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--label", default=None, help="short tag for the run folder")
    args = parser.parse_args()
    run_dir = regenerate(args.manifest, args.label)
    pngs = sorted(run_dir.rglob("*.png"))
    print(f"{run_dir}  ({len(pngs)} png)")
    for path in pngs:
        print(" ", path.relative_to(run_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
