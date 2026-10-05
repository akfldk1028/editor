"""A fixed set of masses, so two critique rounds compare the same buildings.

Two rubric-anchored rounds have now been run and neither could be read as a
before/after, for different reasons each time. The first pair was ruined by my
own prompt - asking the judges to reuse tag names took the vocabulary from 51
tags to 17 and every count moved for a reason unrelated to the masses. The
second pair used an identical prompt and was ruined by the pipeline instead:
fixing things changes which candidates win their cells, so the two sheets shared
only twelve of sixteen schemes and even those were different variants.

    round 1   sentence-contradicted 32   sentence-invisible 16
    round 2   sentence-contradicted 26   sentence-invisible 32

Something real is probably in there - four wrong-verb sentences were rewritten
between the rounds and `sentence-contradicted` is exactly what those were - but
it cannot be separated from the change in cast.

So this renders a named list, one drawing per sentence, always the same
sentences, with no selection in the loop at all. Coverage and siting spreads are
skipped and the mass is the sentence executed, grown to the site and clipped -
the delivered geometry, not the authored size, because that is where every
failure this branch has chased actually lives.

    python tmp_mass_check/_massv2/tools/bench.py <output-name> [pnu]
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

from backend.app.modules.design.generation.maas.massv2.compile import compile_matrix_form  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.execute import execute as execute_parti  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.fill import fill_to_site  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.grammar import parti_from_record  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.legal import load_legal_site  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.render import render_masses  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.siting import site_open_side_direction  # noqa: E402

ROOT = _mass_paths.workspace_root()
# The parcel is an argument, not a constant. Every fix in this branch is written
# to travel - spans measured on the frame's own axes, voids measured against what
# is standing, strides taken from what `box` actually built, thresholds that are
# package constants or ratios - and none of that is worth anything until the same
# twelve sentences are drawn on a second site.
DEFAULT_PNU = "4115011300106840001"

# Twelve sentences held fixed. Chosen to span what this branch has been chasing:
# the ones that read (ewha, towada, acc, saclay, seattle, sluishuis), the ones a
# fix was aimed at (cctv, amorepacific, kimbell, maison bordeaux, mountain
# dwellings) and the one known to be unsayable (souto moura's narrowing roof).
# Do not edit this list to make a round look better - that is the whole point.
BENCH = (
    "kr_ewha_ecc_valley_walls",
    "nishizawa_towada",
    "kr_acc_gwangju_ring_around_a_sunken_plaza",
    "oma_lab_city_saclay",
    "seattle_platforms_shifted_past_each_other",
    "sluishuis_one_corner_lifted_over_water",
    "cctv_a_loop_stood_up",
    "kr_amorepacific_hollow_cube_and_gardens",
    "kimbell_vaults_with_light_between",
    "oma_maison_bordeaux",
    "mountain_dwellings_parking_is_the_slope",
    "souto_moura_casa_das_historias_low_body",
)


def main() -> int:
    out = ROOT / "runs" / (sys.argv[1] if len(sys.argv) > 1 else "bench")
    pnu = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_PNU
    out.mkdir(parents=True, exist_ok=True)

    corpus = {}
    for path in sorted((ROOT / "inputs").glob("gen-*.json")):
        for scheme in json.loads(path.read_text(encoding="utf-8"))["schemes"]:
            corpus[scheme["name"]] = scheme

    site = load_legal_site(pnu, building_type="제1종근린생활시설")
    buildable = site.plan_at(0.0)
    axis = site_open_side_direction(site) or (1.0, 0.0)
    height = site.floor_height_m * max(
        1, int(site.far_capacity_m2 // max(1.0, site.ground_capacity_m2))
    )
    ring = [(float(x), float(y)) for x, y in site.site_local_utm.exterior.coords[:-1]]

    cards, missing = [], []
    for index, name in enumerate(BENCH, start=1):
        scheme = corpus.get(name)
        if scheme is None:
            missing.append(name)
            continue
        parti = parti_from_record(scheme)
        form = execute_parti(
            parti, buildable=buildable, axis=axis, height_m=height,
            storey_height_m=site.floor_height_m,
        )
        if form is None:
            missing.append(name)
            continue
        source = compile_matrix_form(
            fill_to_site(form, site).fit.form,
            storey_height_m=site.floor_height_m, allowed_at=site.plan_at,
        )
        if source is None:
            missing.append(name)
            continue
        png = out / f"alt-{index:02d}.png"
        render_masses(
            [(name, source, {"thesis": scheme.get("formal_principle", "")})],
            png, site_ring=ring, columns=1, tile=(900, 760),
        )
        cards.append({
            "id": f"alt-{index:02d}",
            "png": str(png.resolve()),
            "scheme": name,
            "principle": scheme.get("formal_principle", ""),
        })

    (out / "vlm-manifest.json").write_text(
        json.dumps({"run": out.name, "cards": cards}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    pairs = [
        [cards[i]["id"], cards[(i + step) % len(cards)]["id"]]
        for step in range(1, 5)
        for i in range(len(cards))
        if i < (i + step) % len(cards)
    ]
    (out / "vlm-pairs.json").write_text(
        json.dumps({"run": out.name, "pairs": pairs}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(f"{len(cards)} masses, {len(pairs)} pairs -> {out}")
    if missing:
        print("missing:", ", ".join(missing))
    return 0


if __name__ == "__main__":
    sys.exit(main())
