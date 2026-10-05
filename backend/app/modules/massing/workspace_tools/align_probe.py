"""What a named sentence scores on the regulating test, and what an edit does.

`regulating_audit` reads a whole run and reports a distribution, which answers
"is the corpus composed" but not "would this sentence be composed if it said
one more thing". This runs one sentence's ops straight through execute and
compile on the working parcel, so an authoring edit can be tried in seconds
instead of a grid pass.

    python tools/align_probe.py <sentence-name> [op-json-to-append ...]

Each extra argument is one op appended to the sentence, and each is reported
as its own row, so a sequence of candidate edits reads as a table.
"""

from backend.app.modules.massing import paths as _mass_paths
from backend.app.modules.design.generation import paths as _design_paths
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime


import json
import sys
from pathlib import Path

from backend.app.modules.massing.workspace_tools.band_probe import corpus  # noqa: E402  (django setup inside)
from backend.app.modules.massing.workspace_tools.finalists import PNU, BUILDING_TYPE  # noqa: E402
from backend.app.modules.massing.workspace_tools.regulating_audit import distinct_parts, regulating_ratio  # noqa: E402

from backend.app.modules.design.generation.maas.massv2.compile import compile_matrix_form  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.execute import execute as execute_parti  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.grammar import parti_from_record  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.legal import load_legal_site  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.siting import site_open_side_direction  # noqa: E402

ROOT = _mass_paths.workspace_root()


def score(ops, site, buildable, axis, height_m):
    parti = parti_from_record({"name": "probe", "ops": ops})
    storey = float(parti.floor_height_m or site.floor_height_m)
    form = execute_parti(parti, buildable=buildable, axis=axis,
                         height_m=height_m, storey_height_m=storey)
    source = compile_matrix_form(form, storey_height_m=storey)
    return regulating_ratio(distinct_parts(source))


def main(name: str, *edits: str) -> int:
    book = corpus()
    parti = book.get(name)
    if parti is None:
        print(f"{name} 없음")
        return 1
    site = load_legal_site(PNU, building_type=BUILDING_TYPE)
    buildable = site.plan_at(0.0)
    axis = site_open_side_direction(site) or (1.0, 0.0)
    asked = max((float(op.get("storeys") or 0) for op in parti["ops"]), default=0.0)
    height_m = max(
        site.floor_height_m * max(
            1, int(site.far_capacity_m2 // max(1.0, site.ground_capacity_m2))),
        asked * site.floor_height_m)

    base = list(parti["ops"])
    rows = [("원문", base)]
    for edit in edits:
        rows.append((edit[:44], base + [json.loads(edit)]))
    print(f"{name} · {site.far_capacity_m2:.0f}㎡ 용적 · 대지 {buildable.area:.0f}㎡")
    for label, ops in rows:
        count, lines = score(ops, site, buildable, axis, height_m)
        print(f"   {label:<46} 부분 {count:2d} · 축 {lines:2d} · "
              f"{count / max(lines, 1):.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
