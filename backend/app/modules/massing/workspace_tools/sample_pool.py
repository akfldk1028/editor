"""Render a sample drawn across the whole pool, not the selector's winners.

The first judging round was run on the delivered shortlist, which is chosen by
`spoken_force`. Testing `spoken_force` against judged quality on a set selected
for `spoken_force` is a selected sample: the relationship inside the winners can
have a different sign from the relationship in the population, and that is
exactly what the first round reported (-0.39, -0.32).

So this draws candidates spread evenly across the objective's own range,
straight out of the compiled pool before `choose` sees it, and renders them the
same way. Same renderer, same tile size, same prompt afterwards.

    python tmp_mass_check/_massv2/tools/sample_pool.py <pnu> <out-dir> [count]
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

from backend.app.modules.design.generation.maas.massv2.ablation import ablate  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.compile import compile_matrix_form  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.execute import execute  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.fill import fill_to_site  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.grammar import parti_from_record  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.legal import load_legal_site  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.measure import measure_form  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.plausibility import assess  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.render import render_masses  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.siting import site_open_side_direction  # noqa: E402


def main() -> int:
    pnu = sys.argv[1]
    out = Path(sys.argv[2])
    want = int(sys.argv[3]) if len(sys.argv) > 3 else 24
    out.mkdir(parents=True, exist_ok=True)

    site = load_legal_site(pnu, building_type="제1종근린생활시설")
    buildable = site.plan_at(0.0)
    axis = site_open_side_direction(site) or (1.0, 0.0)
    storeys = max(1, int(site.far_capacity_m2 // max(1.0, site.ground_capacity_m2)))
    height = site.floor_height_m * storeys

    corpus = {}
    for path in sorted(_mass_paths.workspace_root() / 'inputs'.glob("gen-*.json")):
        for scheme in json.loads(path.read_text(encoding="utf-8"))["schemes"]:
            corpus[scheme["name"]] = scheme

    rows = []
    for name, scheme in sorted(corpus.items()):
        parti = parti_from_record(scheme)
        if parti is None:
            continue
        form = execute(parti, buildable=buildable, axis=axis, height_m=height,
                       storey_height_m=site.floor_height_m)
        if form is None:
            continue
        filled = fill_to_site(form, site)
        source = compile_matrix_form(filled.fit.form, storey_height_m=site.floor_height_m,
                                     allowed_at=site.plan_at)
        if source is None:
            continue
        m = measure_form(source)
        p = assess(source, parcel_area_m2=site.parcel_area_m2,
                   max_slenderness=99.0, floor_height_m=site.floor_height_m,
                   building_type=site.building_type)
        a = ablate(parti, buildable=buildable, axis=axis, height_m=height,
                   site=site, storey_height_m=site.floor_height_m)
        rows.append({
            "name": name, "source": source, "form": filled.fit.form,
            "thesis": scheme.get("formal_principle") or scheme.get("secondary_language") or name,
            "spoken_force": a.force,
            "articulation": m.articulation(),
            "convexity_drop": m.convexity_drop,
            "plan_void_ratio": m.plan_void_ratio,
            "section_change": m.section_change,
            "band_count": m.band_count,
            "slenderness": p.slenderness,
            "ground_take": filled.fit.ground_area_m2 / max(site.ground_capacity_m2, 1e-9),
            "far_utilization": filled.fit.gross_floor_area_m2 / max(filled.fit.far_capacity_m2, 1e-9),
        })

    # Even coverage of the objective's own range, not the top of it.
    rows.sort(key=lambda r: r["spoken_force"])
    if len(rows) > want:
        step = len(rows) / want
        rows = [rows[int(i * step)] for i in range(want)]

    alts = []
    site_ring = list(buildable.exterior.coords)
    for index, row in enumerate(rows, start=1):
        png = out / f"alt-{index:02d}.png"
        render_masses(
            [(row["name"], row["source"], {"thesis": row["thesis"]})],
            png, site_ring=site_ring, columns=1, tile=(900, 760),
        )
        alts.append({
            "index": index, "png": png.name, "name": row["name"],
            "thesis": row["thesis"],
            **{k: row[k] for k in (
                "spoken_force", "articulation", "convexity_drop", "plan_void_ratio",
                "section_change", "band_count", "slenderness", "ground_take",
                "far_utilization")},
        })
    (out / "alts.json").write_text(
        json.dumps({"alternatives": alts}, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "objectives.json").write_text(
        json.dumps(alts, ensure_ascii=False, indent=1), encoding="utf-8")
    lo, hi = alts[0]["spoken_force"], alts[-1]["spoken_force"]
    print("%d rendered, spoken_force %.3f .. %.3f" % (len(alts), lo, hi))
    return 0


if __name__ == "__main__":
    sys.exit(main())
