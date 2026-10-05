"""The architect picks: the grid proposes, a person chooses.

Blind judging measured the top of this pipeline's pool at roughly one
fault-free drawing in four, which is a normal hit rate for massing studies
and the reason the final say was moved to eyes (관8). This tool takes the
same principle one step further back: instead of shipping one winner per
cell, it renders the strongest few per cell as one gallery, so the person
the sheet is for can pick from the pool the machine would otherwise pick
from alone.

    python tools/picksheet.py <run> [per_cell] [style]   # style: massing|clay
"""

from backend.app.modules.massing import paths as _mass_paths
from backend.app.modules.design.generation import paths as _design_paths
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime


import json
import sys
from collections import defaultdict
from pathlib import Path

from backend.app.modules.massing.workspace_tools.finalists import PNU, rebuild, scheme_of, BUILDING_TYPE  # noqa: E402  (django setup inside)

from backend.app.modules.design.generation.maas.massv2.legal import load_legal_site  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.render import render_masses  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.siting import site_open_side_direction  # noqa: E402

ROOT = _mass_paths.workspace_root()


def main(run: str, per_cell: int = 3, style: str = "massing") -> int:
    folder = ROOT / "runs" / run
    out = ROOT / "runs" / f"{run}-pick"
    out.mkdir(parents=True, exist_ok=True)
    summary = json.loads((folder / "massv2-summary.json").read_text(encoding="utf-8"))
    # The floor on 용적률 use belongs to the overseas edition, where the form
    # decides its own size and one that used a third of the cap has left the
    # site unbuilt. On the korea edition the size comes from a 실별 소요면적표
    # and 용적률 answers "was the brief met", so the same floor threw away
    # 2,148 of 2,160 lawful masses on the 효돈동 schedule - the exact confusion
    # `--track` was written to prevent.
    korea = (summary.get("provenance") or {}).get("track") == "korea"
    # The same schedule the grid sized these masses to, so the tile is the
    # building its row describes rather than the one the parcel alone would
    # have grown.
    schedule = None
    brief = (summary.get("provenance") or {}).get("programme")
    if korea and brief:
        from backend.app.modules.design.generation.maas.massv2 import program as programme
        book = json.loads((ROOT / "inputs" / "programs-korean.json")
                          .read_text(encoding="utf-8"))
        share = book.get("shared_area_share_of_gross")
        record = next((r for r in book["schedules"] if r.get("name") == brief), None)
        if record is not None:
            schedule = programme.schedule_from_record(
                record, shared_share_of_gross=share)

    def in_winners_envelope(r) -> bool:
        """Where fifteen surveyed Korean public winners actually sit.

        Height 10-20 m and a footprint of 400-800 m2 - not a preference but
        arithmetic: on a 700-2,600 m2 site, statutory landscaping, parking and
        an entry court leave one footprint of that size, and the 30-35% shared
        area those briefs mandate ties it to a single core. A mass outside it
        is not a low-scoring Korean competition mass, it is a different kind of
        building. 482 of this run's 2,160 lawful masses are inside, from 59
        families across all sixteen cells, so this selects rather than starves.
        """
        measured = r.get("measurement") or {}
        height = measured.get("height_m") or 0.0
        ground = (r.get("legal_fit") or {}).get("ground_area_m2") or 0.0
        # And a court on the ground. Counting the subjects of fifteen winning
        # 설계설명 gives 마당·틈·골목·데크 over the mass itself every time, and
        # a void eight floors up is a light well, not a 마당.
        #
        # ⚠️ This read `band_profile[0][1]` first and that is not the ground.
        # The array is not one entry per band - i_bakgong_gori reports
        # band_count 8 against fifteen entries, most of them zero, with the
        # courtyard showing at indices 2, 9, 11 and 13 - so index 0 returned
        # 0.000 for a ring whose plan is 27% open. Every gabled and courtyard
        # sentence was cut by that, and I read the wreckage as "roofs and
        # courts are in conflict". They are not; the measure was.
        #
        # `plan_void_ratio` is the whole mass rather than the ground alone, so
        # a light well eight floors up still counts here. That is the looser
        # reading, and the honest one until the grade-level court is measured
        # from geometry rather than from an array whose indexing I guessed.
        return 10.0 <= height <= 20.0 and 400.0 <= ground <= 800.0

    recs = [
        r for r in summary["records"]
        if "plausibility" in r and r["plausibility"]["occupiable"]
        and (in_winners_envelope(r) if korea else r["far_utilization"] >= 0.375)
    ]
    parcel = float(summary["site"]["parcel_area_m2"])
    far_ratio = float(summary["site"]["far_capacity_m2"]) / parcel

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

    cells = sorted({r["cell"] for r in recs})
    picks = []
    index = 0
    # One family, one appearance *per stature band* - not once in the whole
    # gallery. Ranked per cell alone, one strong family filled eight of
    # forty-four frames and the sheet was a worse offer than eight families
    # nobody had seen; deduped globally instead, a family that wins a seated
    # cell can never appear as the tower it also has, and the growth work that
    # raised twenty-seven families showed up on five tiles. A village at 8 m
    # and the same village at 40 m are two different offers to the person
    # choosing. Stature is the axis, so it is the unit of variety too, and a
    # family can still appear at most four times.
    # A family already on the sheet somewhere takes a slot only when no family
    # nobody has seen can fill it: fresh first, repeats after. Without that,
    # per-band dedup alone spent forty-six frames on thirty-two families.
    seen = set()
    families: dict[str, int] = defaultdict(int)
    # One seat per cell for a verb nobody has heard yet.
    #
    # Ranking a cell by spoken_force alone emptied the sheet of thirteen verbs -
    # gable, mansard and butterfly, so no roofs; twist, skew and rotate, so
    # nothing turns; merge, nest, interlock and intersect, so nothing engages
    # anything else - and what was left read as orthogonal prisms with holes cut
    # in them. They were not refused by any gate: nine families and eighty-one
    # variants of them cleared physics, the winners' envelope and the court, and
    # then lost the ranking. hertzberger sat 40th of 62 in its own cell at 0.44
    # against a 1.00.
    #
    # spoken_force is also the measure a blind round of 62 pairs found does not
    # predict quality (+0.27), so letting it decide alone spends the whole sheet
    # on one number that was tested and failed. One seat, not the cell: the rest
    # of the row is still ranked, so this widens the offer without handing it
    # over.
    def verbs_of(record) -> set[str]:
        scheme = corpus.get(scheme_of(record["name"])) or {}
        return {str(op.get("op")) for op in scheme.get("ops", []) if op.get("op")}

    # Reserve a seat for the rarest verbs first, not for whichever verb the
    # top-ranked candidate happens to carry. Promoting "any unseen verb" per
    # cell was tried and moved one of thirteen: the common verbs are held by
    # high-ranked candidates, so they take the seat and the rare ones stay
    # unheard. Walking the verbs by how rare they are in the pool, and giving
    # each its best-ranked carrier, targets the ones actually missing.
    pool_verbs: dict[str, int] = defaultdict(int)
    for record in recs:
        for verb in verbs_of(record):
            pool_verbs[verb] += 1
    reserved: dict[str, list] = defaultdict(list)
    spoken: set[str] = set()

    def seat(verb: str, per_cell_cap: int) -> bool:
        carriers = sorted(
            (r for r in recs if verb in verbs_of(r)),
            key=lambda r: r.get("spoken_force") or 0.0, reverse=True,
        )
        for carrier in carriers:
            if len(reserved[carrier["cell"]]) >= per_cell_cap:
                continue
            if any(scheme_of(x["name"]) == scheme_of(carrier["name"])
                   for xs in reserved.values() for x in xs):
                continue
            reserved[carrier["cell"]].append(carrier)
            spoken.update(verbs_of(carrier))
            return True
        return False

    # Two passes, one seat per cell in the first. Filling to per_cell - 1 in a
    # single pass let the verbs that come early - the rare ones - take two
    # seats in the same cell, and by the time a verb with many carriers was
    # reached every cell those carriers sit in was full: twist had thirty
    # candidates and all thirty were refused a seat. Spreading first, then
    # widening, seats the same rare verbs and leaves room for the rest.
    order = sorted(pool_verbs.items(), key=lambda kv: kv[1])
    for cap in (1, max(1, per_cell - 1)):
        for verb, _count in order:
            if verb in spoken:
                continue
            seat(verb, cap)

    # A seat per cell for a scheme that actually opens a court.
    #
    # This was a filter on the whole pool and it was the largest single loss on
    # the sheet: thirteen sentences were held by it, and the list is 마을,
    # 박공열, 돌린 판, 비트는 탑 - none of which make a courtyard, and none of
    # which were ever going to. The survey of fifteen winners says the 마당 is
    # the subject of the winning descriptions; it does not say every scheme
    # carries one. Requiring it of the sheet rather than of each tile keeps the
    # court present in every cell and lets a village be a village.
    def court_of(record) -> float:
        return (record.get("measurement") or {}).get("plan_void_ratio") or 0.0

    for cell in {r["cell"] for r in recs}:
        if any(court_of(x) >= 0.05 for x in reserved.get(cell) or []):
            continue
        if len(reserved[cell]) >= max(1, per_cell - 1):
            continue
        for carrier in sorted((r for r in recs if r["cell"] == cell
                               and court_of(r) >= 0.05),
                              key=lambda r: r.get("spoken_force") or 0.0,
                              reverse=True):
            if any(scheme_of(x["name"]) == scheme_of(carrier["name"])
                   for xs in reserved.values() for x in xs):
                continue
            reserved[cell].append(carrier)
            break

    seen = set()
    for cell in cells:
        band = cell.split("|")[0]
        ranked = sorted(
            (r for r in recs if r["cell"] == cell),
            key=lambda r: r.get("spoken_force") or 0.0, reverse=True,
        )
        held = reserved.get(cell) or []
        ranked = held + [r for r in ranked if r not in held]
        row = []
        for r in ranked:
            name = scheme_of(r["name"])
            fam = (name, band)
            # A family may show at two statures, never three. Ordering by
            # freshness instead was tried and does nothing here: there are
            # always enough unseen families to fill every slot, so no second
            # stature ever gets one and the sheet stays what it was.
            if fam in seen or families[name] >= 2:
                continue
            seen.add(fam)
            families[name] += 1
            row.append(r)
            if len(row) >= per_cell:
                break
        for r in row:
            rec = corpus[scheme_of(r["name"])]
            # The budget the grid handed this sentence, not the parcel's own.
            # `generate_massv2._height_budget` raises it to whatever `storeys`
            # the sentence declares, and passing the parcel's four-storey
            # default here drew a different, shorter building than the row's
            # numbers describe: i_bakgong_gori was measured at 48.6 m and drawn
            # at 11.5 m, on a sheet whose whole purpose is to be looked at.
            asked = max((float(op.get("storeys") or 0)
                         for op in rec.get("ops", [])), default=0.0)
            budget = max(height, asked * site.floor_height_m)
            src = rebuild(r["name"], corpus, site, buildable, axis, budget,
                          schedule=schedule)
            if src is None:
                continue
            index += 1
            png = out / f"pick-{index:02d}.png"
            render_masses(
                [(r["name"], src, {"thesis": rec.get("formal_principle", "")})],
                png, site_ring=ring, columns=1, tile=(900, 760), style=style,
            )
            ground = (r.get("legal_fit") or {}).get("ground_area_m2") or 0.0
            picks.append({
                "id": index, "png": png.name, "cell": cell, "name": r["name"],
                "family": scheme_of(r["name"]),
                "principle": rec.get("formal_principle", ""),
                "height_m": (r.get("measurement") or {}).get("height_m"),
                "far_pct": round(r["far_utilization"] * far_ratio * 100),
                "coverage_pct": round(ground / parcel * 100),
            })
    (out / "picks.json").write_text(
        json.dumps({"run": run, "picks": picks}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(f"{len(picks)} picks -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(
        sys.argv[1],
        int(sys.argv[2]) if len(sys.argv) > 2 else 3,
        sys.argv[3] if len(sys.argv) > 3 else "massing",
    ))
