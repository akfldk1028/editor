"""The arbitration stage: a VLM decides each cell final, not a proxy.

The full-set blind round measured every numeric judge this pipeline has
against pairwise VLM preference and none survived - spoken_force +0.27,
convexity -0.25, section +0.12 - while the judges' fault tags (one-lump,
envelope-residue, sentence-invisible) separated winners from losers cleanly.
Geometry proxies rank candidates well enough to shortlist; they cannot be
trusted with the final. So the grid's per-cell winner meets the strongest
different-family challenger in its cell, both rebuilt through the same
deterministic path the grid used, and a blind pairwise judgement takes the
cell. (QD-LLMs, GECCO 2026: vision-language evaluation in the loop.)

    python tools/finalists.py plan  <run>   -> renders + vlm-manifest/pairs
    python tools/finalists.py apply <run>   -> arbitrated alts.json from verdicts
"""

from backend.app.modules.massing import paths as _mass_paths
from backend.app.modules.design.generation import paths as _design_paths
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime


import json
import shutil
from dataclasses import replace
import sys
from pathlib import Path

import os

import django
ensure_design_runtime()

from backend.app.modules.design.generation.maas.massv2.compile import compile_matrix_form  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.execute import execute as execute_parti  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.execute import delivered as delivered_form  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.fill import fill_to_site  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.delivery_gate import stamp_authored_composition
from backend.app.modules.design.generation.maas.massv2.grammar import declared_height_m, declared_stature, parti_from_record
from backend.app.modules.design.generation.maas.massv2.legal import load_legal_site  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.render import render_masses  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.siting import site_open_side_direction, spread_across_siting
from backend.app.modules.design.generation.maas.massv2.variations import spread_across_coverage  # noqa: E402

ROOT = _mass_paths.workspace_root()
# The parcel under study. config/massagent.env is the owner (PNU,
# BUILDING_TYPE, exported by the skills); these literals are the fallback
# for a bare tool run, and the reason a parcel change once moved mass-run
# but not judging or baking.
PNU = os.environ.get("PNU") or "4115011300106840001"
from backend.app.modules.design.generation.maas.massv2.parcel_policy import default_building_type
BUILDING_TYPE = default_building_type(PNU, os.environ.get("BUILDING_TYPE"))


def scheme_of(name: str) -> str:
    return name.split("~")[0].split("^")[0]


def rebuild(name: str, corpus, site, buildable, axis, height, schedule=None,
            programme_weight: float = 1.0, diagnostics=None):
    """One variant's delivered geometry, down the same path the grid walked."""

    rec = corpus.get(scheme_of(name))
    if rec is None:
        return None
    parti = parti_from_record(rec)
    if parti is None:
        return None
    storey = float(parti.floor_height_m or site.floor_height_m)
    # Callers supply only the parcel base or an actual external brief budget.
    # This owner applies the declaration at the scheme's own storey height,
    # just as the generator does. A site-ruler declaration precomputed by a
    # caller would silently inflate the source and cannot be undone by max().
    height = max(float(height), declared_height_m(rec, storey))
    form = execute_parti(
        parti, buildable=buildable, axis=axis, height_m=height,
        storey_height_m=storey,
    )
    if form is None:
        return None
    # The grid stamps the declared storey count onto the form and the growth
    # loop reads it - a sentence that says how tall it is is not held to the
    # parcel's average. Rebuilding without the stamp grew every tile as if it
    # had said nothing, so the sheet drew one building beside another
    # building's numbers: i_bakgong_gori was measured at 48.6 m and drawn at
    # 11.5 m. Same stamp, same shape.
    asked = max((float(op.get("storeys") or 0) for op in rec.get("ops", [])),
                default=0.0)
    if asked > 0.0:
        form = replace(form, extra={**dict(form.extra), **declared_stature(rec)})
    form = stamp_authored_composition(form, storey_m=storey)
    # Before the variants, exactly where the grid does it: the command sizes a
    # scheme to its 실별 소요면적표 and only then spreads it across coverage
    # bands and sitings. Applying the brief afterwards instead reshaped a
    # figure the variant had already settled, and the tile came out on either
    # side of its row - big_gammel_hellerup_yard 52% over, b_madang_gori 18%
    # under.
    if schedule is not None:
        from backend.app.modules.design.generation.maas.massv2 import program as programme
        form = programme.resized_to(
            form, schedule, weight=programme_weight, storey_height_m=storey,
        )
    candidates = [form]
    candidates += spread_across_coverage(
        form,
        ground_capacity_m2=site.ground_capacity_m2,
        far_capacity_m2=site.far_capacity_m2,
        floor_height_m=site.floor_height_m,
    )
    open_side = site_open_side_direction(site)
    for base in list(candidates):
        # The shared owner stamps extra['siting']; without it fit_to_site
        # would seat this already-positioned variant a second time.
        candidates.extend(spread_across_siting(base, buildable=buildable, open_side=open_side))
    target = next((c for c in candidates if c.name == name), None)
    if target is None:
        return None
    # The korea edition sizes a scheme to its 실별 소요면적표 before it grows,
    # and rebuilding without that step drew a different building beside the
    # row's numbers: a_one_bend's tile measured 3,059 m2 against the 1,547 m2
    # its record reports, because the brief never shrank it. Same rule, same
    # function, two answers - the tenth time in this package that one building
    # was measured twice.
    wanted = target.extra.get("programme_target")
    # `resized_to` only redistributes plan between volumes; what holds the whole
    # scheme to the brief is the growth loop's target, and the grid passes it as
    # a share of the parcel's cap. Rebuilding without it grew every tile to the
    # language default instead - 0.85 of 6,242 m2 against a 1,546 m2 brief, so
    # a_one_bend was drawn at 4,127 m2 beside a row saying 1,547.
    fitted = fill_to_site(
        target, site,
        target_utilization=(float(wanted) / max(site.far_capacity_m2, 1e-9)
                            if wanted else None),
    ).fit
    if not fitted.satisfied:
        return None
    grown = fitted.form
    # The same last step the command takes, so what this tool measures is what
    # the run ships. A named line survives as an intent through the growth loop
    # rather than as a position, and it is re-asserted here.
    source = compile_matrix_form(
        delivered_form(grown, axis=axis, storey_m=storey),
        storey_height_m=storey, allowed_at=site.plan_at,
    )
    if source is not None:
        from backend.app.modules.design.generation.maas.massv2.ablation import gap_evidence
        gap = gap_evidence(source)
        if diagnostics is not None:
            diagnostics['gap'] = gap
        if not gap['satisfied']:
            return None
    return source


def plan(run: str) -> int:
    folder = ROOT / "runs" / run
    out = ROOT / "runs" / f"{run}-arb"
    out.mkdir(parents=True, exist_ok=True)
    alts = json.loads((folder / "alts.json").read_text(encoding="utf-8"))["alternatives"]
    summary = json.loads((folder / "massv2-summary.json").read_text(encoding="utf-8"))
    recs = [r for r in summary["records"] if "plausibility" in r]

    corpus = {}
    for p in sorted((ROOT / "inputs").glob("gen-*.json")):
        for s in json.loads(p.read_text(encoding="utf-8"))["schemes"]:
            corpus[s["name"]] = s

    site = load_legal_site(PNU, building_type=BUILDING_TYPE)
    buildable = site.plan_at(0.0)
    axis = site_open_side_direction(site) or (1.0, 0.0)
    height = site.floor_height_m * max(
        1, int(site.far_capacity_m2 // max(1.0, site.ground_capacity_m2))
    )
    ring = [(float(x), float(y)) for x, y in site.site_local_utm.exterior.coords[:-1]]

    # A challenger is the strongest candidate in the cell from a family the
    # sheet does not already hold - anywhere. Chosen per-cell without that
    # constraint, one strong all-rounder challenged ten cells and the blind
    # judges, who see one pair at a time, handed it five: the arbitration
    # was quietly undoing the sheet's own first rule, one sentence one tile.
    cards, pairs, duels = [], [], []
    taken = {scheme_of(a["name"]) for a in alts}
    used = set()
    for a in alts:
        cell = None
        for r in recs:
            if r["name"] == a["name"]:
                cell = r["cell"]; break
        if cell is None:
            continue
        family = scheme_of(a["name"])
        rivals = [
            r for r in recs
            if r["cell"] == cell
            and scheme_of(r["name"]) not in taken
            and scheme_of(r["name"]) not in used
            and r["plausibility"]["occupiable"] and r["far_utilization"] >= 0.375
        ]
        if not rivals:
            duels.append({"cell": a["cell"], "winner": a["name"], "challenger": None})
            continue
        rival = max(rivals, key=lambda r: r.get("spoken_force") or 0.0)
        used.add(scheme_of(rival["name"]))
        duels.append({"cell": a["cell"], "winner": a["name"], "challenger": rival["name"], "kind": "family",
                      "challenger_record": {
                          "far_utilization": rival["far_utilization"],
                          "gfa_m2": rival.get("gfa_m2"),
                          "ground_area_m2": (rival.get("legal_fit") or {}).get("ground_area_m2"),
                      }})

    # The second duel: the chosen variant against its own family's tallest
    # same-cell variant. Measured on uij-dns, five of fifteen cell winners
    # were crushed variants of their family - seattle shipped 15 m out of a
    # family reaching 47 - because all variants of a sentence share one
    # spoken_force and the tie is broken by the same proxies the blind round
    # failed. Which variant of a family shows is a judgement of eyes too.
    for a in alts:
        cell = None
        chosen = None
        for r in recs:
            if r["name"] == a["name"]:
                cell = r["cell"]; chosen = r; break
        if chosen is None:
            continue
        family = scheme_of(a["name"])
        kin = [
            r for r in recs
            if r["cell"] == cell and scheme_of(r["name"]) == family
            and r["name"] != a["name"]
            and r["plausibility"]["occupiable"] and r["far_utilization"] >= 0.375
        ]
        if not kin:
            continue
        tall = max(kin, key=lambda r: (r.get("measurement") or {}).get("height_m") or 0.0)
        if ((tall.get("measurement") or {}).get("height_m") or 0.0) <            ((chosen.get("measurement") or {}).get("height_m") or 0.0) + 2.0:
            continue
        duels.append({"cell": a["cell"], "winner": a["name"], "challenger": tall["name"],
                      "kind": "variant",
                      "challenger_record": {
                          "far_utilization": tall["far_utilization"],
                          "gfa_m2": tall.get("gfa_m2"),
                          "ground_area_m2": (tall.get("legal_fit") or {}).get("ground_area_m2"),
                      }})

    index = 0
    id_of = {}
    for duel in duels:
        for name in (duel["winner"], duel["challenger"]):
            if name is None or name in id_of:
                continue
            src = rebuild(name, corpus, site, buildable, axis, height)
            if src is None:
                continue
            index += 1
            cid = f"alt-{index:02d}"
            id_of[name] = cid
            rec = corpus[scheme_of(name)]
            png = out / f"{cid}.png"
            render_masses(
                [(name, src, {"thesis": rec.get("formal_principle", "")})],
                png, site_ring=ring, columns=1, tile=(900, 760),
            )
            cards.append({
                "id": cid, "png": str(png.resolve()), "scheme": name,
                "principle": rec.get("formal_principle", ""),
            })
    for duel in duels:
        w, c = duel["winner"], duel["challenger"]
        if c and w in id_of and c in id_of:
            pairs.append([id_of[w], id_of[c]])
            duel["pair"] = [id_of[w], id_of[c]]

    (out / "vlm-manifest.json").write_text(
        json.dumps({"run": f"{run}-arb", "cards": cards}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    (out / "vlm-pairs.json").write_text(
        json.dumps({"run": f"{run}-arb", "pairs": pairs}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    (out / "duels.json").write_text(
        json.dumps({"duels": duels}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(cards)} cards, {len(pairs)} duels -> {out}")
    return 0


# A pairwise judge can name the better card but never refuse both, so a cell
# whose two candidates are both bad ships the less bad one wearing the fault
# tags that say so. The repechage reads those tags off the standing winners -
# the tags were the one signal the blind round validated - and stages one more
# duel for each tagged cell against the strongest family the sheet has not
# heard from. The veto the pair judge cannot say, the next candidate says.
FATAL = {"sentence-contradicted", "sentence-invisible", "no-figure",
         "reads-as-one-lump", "pieces-look-random"}


def repechage(run: str) -> int:
    folder = ROOT / "runs" / run
    out = ROOT / "runs" / f"{run}-arb"
    duels = json.loads((out / "duels.json").read_text(encoding="utf-8"))["duels"]
    manifest = json.loads((out / "vlm-manifest.json").read_text(encoding="utf-8"))
    cards = {c["id"]: c for c in manifest["cards"]}
    verdicts = []
    for f in sorted(out.glob("vlm-verdict-*.json")):
        verdicts += json.loads(f.read_text(encoding="utf-8"))["verdicts"]
    won = {(v["a"], v["b"]): v for v in verdicts}
    summary = json.loads((folder / "massv2-summary.json").read_text(encoding="utf-8"))
    recs = [r for r in summary["records"] if "plausibility" in r]

    corpus = {}
    for p in sorted((ROOT / "inputs").glob("gen-*.json")):
        for s in json.loads(p.read_text(encoding="utf-8"))["schemes"]:
            corpus[s["name"]] = s
    site = load_legal_site(PNU, building_type=BUILDING_TYPE)
    buildable = site.plan_at(0.0)
    axis = site_open_side_direction(site) or (1.0, 0.0)
    height = site.floor_height_m * max(
        1, int(site.far_capacity_m2 // max(1.0, site.ground_capacity_m2))
    )
    ring = [(float(x), float(y)) for x, y in site.site_local_utm.exterior.coords[:-1]]

    # Every family the arbitrated sheet holds or has already auditioned.
    heard = set()
    for d in duels:
        heard.add(scheme_of(d["winner"]))
        if d.get("challenger"):
            heard.add(scheme_of(d["challenger"]))

    index = max((int(c["id"].split("-")[1]) for c in manifest["cards"]), default=0)
    pairs = []
    staged = 0
    for d in [x for x in duels if x.get("pair") and x.get("kind", "family") == "family"]:
        v = won.get(tuple(d["pair"]))
        if v is None:
            continue
        win_id = v["winner"]
        faults = set(v["a_faults" if win_id == v["a"] else "b_faults"])
        if not (faults & FATAL):
            continue
        holder = cards[win_id]["scheme"]
        cell = next((r["cell"] for r in recs if r["name"] == holder), None)
        rivals = [
            r for r in recs
            if r["cell"] == cell and scheme_of(r["name"]) not in heard
            and r["plausibility"]["occupiable"] and r["far_utilization"] >= 0.375
        ]
        if not rivals:
            continue
        rival = max(rivals, key=lambda r: r.get("spoken_force") or 0.0)
        heard.add(scheme_of(rival["name"]))
        src = rebuild(rival["name"], corpus, site, buildable, axis, height)
        if src is None:
            continue
        index += 1
        cid = f"alt-{index:02d}"
        rec = corpus[scheme_of(rival["name"])]
        png = out / f"{cid}.png"
        render_masses(
            [(rival["name"], src, {"thesis": rec.get("formal_principle", "")})],
            png, site_ring=ring, columns=1, tile=(900, 760),
        )
        manifest["cards"].append({
            "id": cid, "png": str(png.resolve()), "scheme": rival["name"],
            "principle": rec.get("formal_principle", ""),
        })
        duels.append({"cell": d["cell"], "winner": holder, "challenger": rival["name"],
                      "kind": "repechage", "pair": [win_id, cid],
                      "challenger_record": {
                          "far_utilization": rival["far_utilization"],
                          "gfa_m2": rival.get("gfa_m2"),
                          "ground_area_m2": (rival.get("legal_fit") or {}).get("ground_area_m2"),
                      }})
        pairs.append([win_id, cid])
        staged += 1
    (out / "vlm-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "duels.json").write_text(
        json.dumps({"duels": duels}, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "vlm-pairs-repechage.json").write_text(
        json.dumps({"run": f"{run}-arb", "pairs": pairs}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(f"{staged} repechage duels -> vlm-pairs-repechage.json")
    return 0


def apply(run: str) -> int:
    folder = ROOT / "runs" / run
    out = ROOT / "runs" / f"{run}-arb"
    alts = json.loads((folder / "alts.json").read_text(encoding="utf-8"))
    duels = json.loads((out / "duels.json").read_text(encoding="utf-8"))["duels"]
    cards = {c["id"]: c for c in json.loads(
        (out / "vlm-manifest.json").read_text(encoding="utf-8"))["cards"]}
    verdicts = []
    for f in sorted(out.glob("vlm-verdict-*.json")):
        verdicts += json.loads(f.read_text(encoding="utf-8"))["verdicts"]
    won = {(v["a"], v["b"]): v for v in verdicts}
    summary = json.loads((folder / "massv2-summary.json").read_text(encoding="utf-8"))
    parcel = float(summary["site"]["parcel_area_m2"])
    far_ratio = float(summary["site"]["far_capacity_m2"]) / parcel

    corpus = {}
    for p in sorted((ROOT / "inputs").glob("gen-*.json")):
        for s in json.loads(p.read_text(encoding="utf-8"))["schemes"]:
            corpus[s["name"]] = s

    swaps = 0
    for a in alts["alternatives"]:
        # Family first (who holds the cell), then variant (which drawing of
        # the holder shows). A variant duel staged for the original winner is
        # moot once its family lost the cell.
        for kind in ("family", "variant", "repechage"):
            duel = next(
                (d for d in duels
                 if d["winner"] == a["name"] and d.get("pair")
                 and d.get("kind", "family") == kind),
                None,
            )
            if duel is None:
                continue
            v = won.get(tuple(duel["pair"]))
            if v is None:
                continue
            w_id, c_id = duel["pair"]
            keep = v["winner"] == w_id
            chosen = w_id if keep else c_id
            card = cards[chosen]
            if not keep:
                swaps += 1
                rec = duel.get("challenger_record") or {}
                a["name"] = card["scheme"]
                a["thesis"] = corpus[scheme_of(card["scheme"])].get("formal_principle", "")
                if rec.get("far_utilization") is not None:
                    a["용적률"] = f"{rec['far_utilization']*far_ratio*100:.0f}%"
                if rec.get("ground_area_m2"):
                    a["건폐율"] = f"{rec['ground_area_m2']/parcel*100:.0f}%"
            a["png"] = f"{chosen}.png"
            a["arbitrated"] = True
            a["arb_why"] = v.get("why", "")
    (out / "alts.json").write_text(
        json.dumps(alts, ensure_ascii=False, indent=2), encoding="utf-8")
    # carry the summary over so the sheet builder finds it
    shutil.copy(folder / "massv2-summary.json", out / "massv2-summary.json")
    print(f"arbitrated: {swaps} cells swapped -> {out / 'alts.json'}")
    return 0


if __name__ == "__main__":
    mode, run = sys.argv[1], sys.argv[2]
    sys.exit({"plan": plan, "repechage": repechage}.get(mode, apply)(run))
