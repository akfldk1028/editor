"""How much of a mass sits in volumes too thin to be a storey.

`plausibility.viable_band_share` asks whether each volume's *plan* is wide
enough to be a room and never whether it is tall enough to be one, so a
building sliced into half-metre trays reports every band viable. The sheet
showed it: nishizawa_nishinoyama says ten low houses and draws a stack of
trays, 32 volumes over 15.6 m.

    python tools/tray_audit.py <run>
"""

from backend.app.modules.massing import paths as _mass_paths
from backend.app.modules.design.generation import paths as _design_paths
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime


import json
import sys
from pathlib import Path

from backend.app.modules.massing.workspace_tools.finalists import PNU, rebuild, scheme_of, BUILDING_TYPE  # noqa: E402  (django setup inside)

from backend.app.modules.design.generation.maas.massv2.legal import load_legal_site  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.siting import site_open_side_direction  # noqa: E402

ROOT = _mass_paths.workspace_root()


def main(run: str) -> int:
    picks = json.loads((ROOT / "runs" / f"{run}-pick" / "picks.json")
                       .read_text(encoding="utf-8"))["picks"]
    corpus = {}
    for p in sorted((ROOT / "inputs").glob("gen-*.json")):
        for s in json.loads(p.read_text(encoding="utf-8"))["schemes"]:
            corpus[s["name"]] = s
    site = load_legal_site(PNU, building_type=BUILDING_TYPE)
    buildable = site.plan_at(0.0)
    axis = site_open_side_direction(site) or (1.0, 0.0)
    base = site.floor_height_m * max(
        1, int(site.far_capacity_m2 // max(1.0, site.ground_capacity_m2)))

    rows = []
    for p in picks:
        rec = corpus.get(scheme_of(p["name"]))
        if rec is None:
            continue
        asked = max((float(op.get("storeys") or 0)
                     for op in rec.get("ops", [])), default=0.0)
        storey = float(rec.get("floor_height_m") or site.floor_height_m)
        src = rebuild(p["name"], corpus, site, buildable,
                      axis, max(base, asked * site.floor_height_m))
        if src is None:
            continue
        height = float(p["height_m"] or 0.0)
        bulk = thin = 0.0
        for v in src.volumes:
            if v.footprint is None:
                continue
            deep = (v.top_fraction - v.bottom_fraction) * height
            piece = v.footprint.area * max(deep, 0.0)
            bulk += piece
            if deep < storey * 0.9:
                thin += piece
        rows.append({"id": p["id"], "family": p["family"],
                     "volumes": len(src.volumes), "height_m": height,
                     "tray_share": round(thin / bulk, 3) if bulk else 0.0})

    rows.sort(key=lambda r: -r["tray_share"])
    out = ROOT / "runs" / f"{run}-pick" / "trays.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    bad = [r for r in rows if r["tray_share"] > 0.5]
    print(f"{len(rows)} picks, {len(bad)} with over half their bulk in sub-storey slabs")
    for r in rows[:10]:
        print(f"  #{r['id']:02d} {r['family'][:34]:<34} "
              f"volumes {r['volumes']:>2}  tray {r['tray_share']:.0%}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
