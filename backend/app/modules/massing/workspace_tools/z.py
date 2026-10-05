
from backend.app.modules.massing import paths as _mass_paths
from backend.app.modules.design.generation import paths as _design_paths
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime

import json
from pathlib import Path
from backend.app.modules.massing.workspace_tools.finalists import PNU, rebuild, scheme_of, BUILDING_TYPE
from backend.app.modules.design.generation.maas.massv2 import program as programme
from backend.app.modules.design.generation.maas.massv2.legal import load_legal_site
from backend.app.modules.design.generation.maas.massv2.siting import site_open_side_direction
from backend.app.modules.design.generation.maas.massv2.measure import gross_floor_area_m2
ROOT = _mass_paths.workspace_root()
summ = json.loads((ROOT/"runs/uij-brief/massv2-summary.json").read_text(encoding="utf-8"))
recs = {r["name"]: r for r in summ["records"]}
book = json.loads((ROOT/"inputs/programs-korean.json").read_text(encoding="utf-8"))
sched = programme.schedule_from_record(
    next(r for r in book["schedules"] if r["name"] == summ["provenance"]["programme"]),
    shared_share_of_gross=book.get("shared_area_share_of_gross"))
corpus = {}
for p in sorted((ROOT/"inputs").glob("gen-*.json")):
    for s in json.loads(p.read_text(encoding="utf-8"))["schemes"]: corpus[s["name"]] = s
site = load_legal_site(PNU, building_type=BUILDING_TYPE)
buildable = site.plan_at(0.0); axis = site_open_side_direction(site) or (1.0,0.0)
base = site.floor_height_m*max(1,int(site.far_capacity_m2//max(1.0,site.ground_capacity_m2)))
picks = json.loads((ROOT/"runs/uij-brief-pick/picks.json").read_text(encoding="utf-8"))["picks"]
gaps = []
for p in picks:
    rec = corpus[scheme_of(p["name"])]
    asked = max((float(o.get("storeys") or 0) for o in rec["ops"]), default=0.0)
    storey = float(rec.get("floor_height_m") or site.floor_height_m)
    src = rebuild(p["name"], corpus, site, buildable, axis,
                  max(base, asked*site.floor_height_m), schedule=sched)
    if src is None: continue
    drawn = gross_floor_area_m2(src, floor_height_m=storey)
    said = float(recs[p["name"]].get("gfa_m2") or 0.0)
    gaps.append((abs(drawn-said)/max(said,1.0), p["id"], p["family"], drawn, said))
gaps.sort(reverse=True)
lines = ["픽 %d개 · 2%% 초과 %d개 · 최대 %.1f%%" % (
    len(gaps), sum(1 for g in gaps if g[0] > 0.02), gaps[0][0]*100 if gaps else 0)]
for g, i, f, d, s in gaps[:6]:
    lines.append("  #%02d %-28s 그림 %.0f vs 기록 %.0f (%.0f%%)" % (i, f[:28], d, s, g*100))
Path("z.txt").write_text("\n".join(lines), encoding="utf-8")
