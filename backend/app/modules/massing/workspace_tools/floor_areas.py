"""The real plan area of each storey, not the average.

`floor_programme` divided 연면적 by the storey count, which is only true of a
prism. A mass that is wide on the ground and narrow above holds its 대회의실
on the floor that can take it, and the average hides that in both directions.
"""

from backend.app.modules.massing import paths as _mass_paths
from backend.app.modules.design.generation import paths as _design_paths
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime


import json, sys
from pathlib import Path
from backend.app.modules.massing.workspace_tools.finalists import PNU, rebuild, scheme_of, BUILDING_TYPE
from backend.app.modules.design.generation.maas.massv2.legal import load_legal_site
from backend.app.modules.design.generation.maas.massv2.measure import storeys_in
from backend.app.modules.design.generation.maas.massv2.siting import site_open_side_direction

ROOT = _mass_paths.workspace_root()


def storey_areas(src, *, height_m: float, storey_m: float) -> list[float]:
    """How much floor each storey holds, from the ground up.

    Sampling the plan at mid-storey was the first version and it undercounts a
    scattered mass badly: a piece sitting between two sample heights is missed
    whole, so i_naneun_maeul's four storeys summed to 1,062 m2 against a
    recorded 연면적 of 1,264 and the village was reported unable to hold a
    brief it may well hold.

    Each volume now contributes to every storey band it overlaps, in
    proportion to how much of that band it occupies - which is the same rule
    `measure.gross_floor_area_m2` uses, so the storeys sum to the 연면적
    rather than to a set of sections through it.
    """

    floors = max(1, round(height_m / max(storey_m, 1e-6)))
    out = [0.0] * floors
    for v in src.volumes:
        if v.footprint is None:
            continue
        deep = (float(v.top_fraction) - float(v.bottom_fraction)) * height_m
        held = storeys_in(deep, floor_height_m=storey_m)
        if held <= 0:
            continue
        base = int((float(v.bottom_fraction) * height_m) // max(storey_m, 1e-6))
        for n in range(int(round(held))):
            level = min(base + n, floors - 1)
            out[level] += float(v.footprint.area)
    return out


def main(run: str) -> int:
    folder = ROOT / "runs" / run
    picks = json.loads((folder.parent / f"{run}-pick" / "picks.json").read_text(encoding="utf-8"))["picks"]
    records = {r["name"]: r for r in json.loads((folder / "massv2-summary.json").read_text(encoding="utf-8"))["records"]}
    corpus = {}
    for p in sorted((ROOT / "inputs").glob("gen-*.json")):
        for s in json.loads(p.read_text(encoding="utf-8"))["schemes"]:
            corpus[s["name"]] = s
    site = load_legal_site(PNU, building_type=BUILDING_TYPE)
    buildable = site.plan_at(0.0)
    axis = site_open_side_direction(site) or (1.0, 0.0)
    base = site.floor_height_m * max(1, int(site.far_capacity_m2 // max(1.0, site.ground_capacity_m2)))

    out = []
    for p in picks:
        rec = corpus.get(scheme_of(p["name"]))
        if rec is None:
            continue
        asked = max((float(op.get("storeys") or 0) for op in rec.get("ops", [])), default=0.0)
        storey = float(rec.get("floor_height_m") or site.floor_height_m)
        src = rebuild(p["name"], corpus, site, buildable, axis, max(base, asked * site.floor_height_m))
        if src is None:
            continue
        areas = storey_areas(src, height_m=float(p["height_m"] or 0.0), storey_m=storey)
        out.append({"id": p["id"], "family": p["family"], "storey_m": storey,
                    "areas_m2": [round(a, 1) for a in areas]})
    path = folder.parent / f"{run}-pick" / "floor_areas.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(out)} picks")
    for r in out[:6]:
        print(f"  #{r['id']:02d} {r['family'][:30]:<30} " +
              " ".join(f"{a:.0f}" for a in r["areas_m2"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
