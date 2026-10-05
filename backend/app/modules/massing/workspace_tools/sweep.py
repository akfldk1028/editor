"""What one authored number actually does to the delivered mass.

Aiming an edit from the deviation table failed seven times out of seven, and
the misses were not small: raising compress on site_best_notch left its
footprint at 394 m2 unchanged, the same edit on keystone_and_socket took it
to 1,146, and cutting c_thrust_ramp's 층수 from five to four made it taller.
The growth loop and the legal fit sit between the sentence and the number, so
the relation is not the monotone one authoring assumes.

This sweeps one parameter through the whole pipeline and prints the curve, so
an edit can be read off rather than guessed.

    python tools/sweep.py <family> <op-index> <param> <v1> <v2> ...
    python tools/sweep.py site_best_notch_extracted_corner 1 ratio 0.5 0.6 0.7 0.8 0.9
"""

from backend.app.modules.massing import paths as _mass_paths
from backend.app.modules.design.generation import paths as _design_paths
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime


import copy
import json
import sys
from pathlib import Path

from backend.app.modules.massing.workspace_tools.finalists import PNU, BUILDING_TYPE  # noqa: E402  (django setup inside)

from backend.app.modules.design.generation.maas.massv2.compile import compile_matrix_form  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.execute import execute as execute_parti  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.fill import fill_to_site  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.grammar import parti_from_record  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.legal import load_legal_site  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.measure import measure_form  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.siting import OPEN_SIDE_SITINGS, SITINGS, site_open_side_direction, place_on_site

ROOT = _mass_paths.workspace_root()


def main(family: str, index: str, param: str, *values: str) -> int:
    corpus = {}
    for path in sorted((ROOT / "inputs").glob("gen-*.json")):
        for s in json.loads(path.read_text(encoding="utf-8"))["schemes"]:
            corpus[s["name"]] = s
    record = corpus[family]
    site = load_legal_site(PNU, building_type=BUILDING_TYPE)
    buildable = site.plan_at(0.0)
    axis = site_open_side_direction(site) or (1.0, 0.0)
    open_side = site_open_side_direction(site)
    sitings = OPEN_SIDE_SITINGS if open_side is not None else SITINGS
    base = site.floor_height_m * max(
        1, int(site.far_capacity_m2 // max(1.0, site.ground_capacity_m2)))

    op_index = int(index)
    print(f"{family}  ops[{op_index}].{param}")
    print(f"{'값':>8}{'높이 m':>9}{'바닥 ㎡':>9}{'연면적':>9}{'비움':>7}  비고")
    for raw in values:
        try:
            value = float(raw)
        except ValueError:
            value = raw
        trial = copy.deepcopy(record)
        trial["ops"][op_index][param] = value
        parti = parti_from_record(trial)
        if parti is None:
            print(f"{raw:>8}  파싱 거부")
            continue
        storey = float(parti.floor_height_m or site.floor_height_m)
        asked = max((float(o.get("storeys") or 0) for o in trial["ops"]), default=0.0)
        form = execute_parti(
            parti, buildable=buildable, axis=axis,
            height_m=max(base, asked * site.floor_height_m), storey_height_m=storey,
        )
        if form is None:
            print(f"{raw:>8}  실행 실패")
            continue
        moved = place_on_site(form, buildable, sitings[0], open_side=open_side) or form
        grown = fill_to_site(moved, site)
        src = compile_matrix_form(grown.fit.form, storey_height_m=storey,
                                  allowed_at=site.plan_at)
        if src is None:
            print(f"{raw:>8}  컴파일 없음")
            continue
        m = measure_form(src)
        fit = grown.fit
        note = "" if fit.satisfied else "법규 미충족"
        print(f"{raw:>8}{m.height_m:>9.1f}{fit.ground_area_m2:>9.0f}"
              f"{fit.gross_floor_area_m2:>9.0f}{m.plan_void_ratio:>7.2f}  {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
