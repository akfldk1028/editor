"""Every authored word's changed share, whole-mass and within-reach, side by side.

The selector reads `spoken_force`, the mean of a sentence's per-word changed
shares. That number is measured against the whole volume, so a word confined
to one storey band - every roof word is - has a ceiling of the band's share of
the building: `gable` capped at 0.17, SANAA's quiet `carve` at 0.12, and both
languages lost every cell without a gate ever touching them. Before the judge
is changed, this bench pins the baseline: the whole corpus, uniformly, no
selection in the loop (a selected sample inverts signs), each word under the
current metric and under the reach-normalised candidate.

    python tmp_mass_check/_massv2/tools/word_shares.py <output-name> [pnu]
"""

from backend.app.modules.massing import paths as _mass_paths
from backend.app.modules.design.generation import paths as _design_paths
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime


import json
import sys
from pathlib import Path

import django

import os

ensure_design_runtime()

from backend.app.modules.design.generation.maas.massv2 import postcondition  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.grammar import parti_from_record  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.legal import load_legal_site  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.siting import site_open_side_direction  # noqa: E402

ROOT = _mass_paths.workspace_root()
DEFAULT_PNU = "4115011300106840001"


def force(values: tuple[float, ...]) -> float:
    said = list(values[1:]) or list(values)
    return sum(said) / max(len(said), 1)


def main() -> int:
    out = ROOT / "runs" / (sys.argv[1] if len(sys.argv) > 1 else "word-shares")
    pnu = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_PNU
    out.mkdir(parents=True, exist_ok=True)

    site = load_legal_site(pnu, building_type="제1종근린생활시설")
    buildable = site.plan_at(0.0)
    axis = site_open_side_direction(site) or (1.0, 0.0)
    height = site.floor_height_m * max(
        1, int(site.far_capacity_m2 // max(1.0, site.ground_capacity_m2))
    )

    rows = []
    for path in sorted((ROOT / "inputs").glob("gen-*.json")):
        for scheme in json.loads(path.read_text(encoding="utf-8"))["schemes"]:
            parti = parti_from_record(scheme)
            if parti is None:
                continue
            storey = float(parti.floor_height_m or site.floor_height_m)
            verdict = postcondition.check_sentence(
                parti, buildable=buildable, axis=axis, height_m=height,
                allowed_at=site.plan_at, storey_height_m=storey,
            )
            rows.append({
                "corpus": path.stem,
                "name": scheme["name"],
                "verbs": list(verdict.declared),
                "silent": list(verdict.silent),
                "changed": [round(v, 4) for v in verdict.changed],
                "reached": [round(v, 4) for v in verdict.reached],
                "force_changed": round(force(verdict.changed), 4),
                "force_reached": round(force(verdict.reached), 4),
            })
            print(
                f"{scheme['name']:48s} {rows[-1]['force_changed']:.3f} -> "
                f"{rows[-1]['force_reached']:.3f}  "
                + " ".join(
                    f"{v}:{c:.2f}/{r:.2f}"
                    for v, c, r in zip(
                        verdict.declared, verdict.changed, verdict.reached
                    )
                )
            )

    (out / "word-shares.json").write_text(
        json.dumps({"pnu": pnu, "rows": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"{len(rows)} sentences -> {out / 'word-shares.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
