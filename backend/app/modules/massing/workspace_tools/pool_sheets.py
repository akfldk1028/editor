"""Every physics-passing mass of a run, drawn - so a person can actually look.

The selection showed 12 of 3,482 and the user rightly asked to see the rest:
the pool had eleven hundred masses of five storeys and more that no sheet
ever surfaced. This renders the WHOLE plausible pool as numbered contact
sheets (48 tiles each), ordered tall-first within family order, with storeys
and FAR on every tile - the browsing surface for a human sweep and for
auditor subagents.

    python tools/pool_sheets.py <run> [out-dir-name]
"""

from backend.app.modules.massing import paths as _mass_paths
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime


from backend.app.modules.design.generation import paths as _design_paths

import json
import sys
from pathlib import Path

from backend.app.modules.massing.workspace_tools.band_probe import corpus, schedule_of  # noqa: E402
from backend.app.modules.massing.workspace_tools.finalists import PNU, rebuild, BUILDING_TYPE  # noqa: E402

from backend.app.modules.design.generation.maas.massv2.legal import load_legal_site  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.render import render_masses  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.siting import site_open_side_direction  # noqa: E402

ROOT = _mass_paths.workspace_root()
# The sheet's geometry in one place: anyone cropping a tile back out of a
# rendered sheet (probe_pair) reads these, so they may never drift apart.
PER_SHEET = 48
COLUMNS = 8
TILE = (300, 270)


# Plan similarity is a browsing hint, never proof of identical 3D mass.
# Keep section, roof and placement alternatives available for human choice.
_SAME_PLAN_IOU = 0.92
_SAME_PROPORTION = 0.25


def _drawing_signature(source):
    """(normalized ground plan, plan proportion, part count), or None."""

    from shapely.ops import unary_union
    from shapely import affinity
    parts = [v.footprint for v in source.volumes
             if v.footprint is not None and not v.footprint.is_empty
             and v.bottom_fraction < 1e-6]
    if not parts:
        parts = [v.footprint for v in source.volumes
                 if v.footprint is not None and not v.footprint.is_empty]
    if not parts:
        return None
    ground = unary_union(parts)
    if ground.is_empty:
        return None
    minx, miny, maxx, maxy = ground.bounds
    width = max(maxx - minx, 1e-9)
    depth = max(maxy - miny, 1e-9)
    plan = affinity.scale(affinity.translate(ground, -minx, -miny),
                          1.0 / width, 1.0 / depth, origin=(0.0, 0.0))
    return plan, width / depth, len(source.volumes)


def _same_drawing(one, two) -> bool:
    plan_a, ratio_a, parts_a = one
    plan_b, ratio_b, parts_b = two
    if parts_a != parts_b or abs(ratio_a - ratio_b) > _SAME_PROPORTION:
        return False
    union = plan_a.union(plan_b).area
    if union <= 1e-9:
        return False
    return plan_a.intersection(plan_b).area / union >= _SAME_PLAN_IOU


def main(run: str, out_name: str = "", mode: str = "") -> int:
    heroes = mode == "--heroes"
    summary = json.loads((ROOT / "runs" / run / "massv2-summary.json")
                         .read_text(encoding="utf-8"))
    book = corpus()
    schedule = schedule_of(run)
    site = load_legal_site(PNU, building_type=BUILDING_TYPE)
    buildable = site.plan_at(0.0)
    axis = site_open_side_direction(site) or (1.0, 0.0)
    base = site.floor_height_m * max(
        1, int(site.far_capacity_m2 // max(1.0, site.ground_capacity_m2)))
    parcel = float(summary["site"]["parcel_area_m2"])

    rows = []
    # The selector's minimum delivered share was retired (explicit plan-only
    # candidates may enter below it), so this sheet no longer hides the low
    # end either: its stated purpose is the WHOLE plausible pool, and the
    # 4%-FAR stubs it once filtered are now labelled by their own numbers.
    MINIMUM_DELIVERED_SHARE = 0.0
    for record in summary["records"]:
        if not (record.get("plausibility") or {}).get("occupiable"):
            continue
        # The same floor the selector stands on: a siting that pushed the
        # mass off the buildable area leaves a lawful 4%-FAR stub, and
        # "tallest variant per sentence" put those sticks on the hero sheet
        # (Maison Bordeaux, Sluishuis at 6% and 4%).
        if float(record.get("far_utilization") or 0.0) < MINIMUM_DELIVERED_SHARE:
            continue
        fit = record.get("legal_fit") or {}
        ground = float(fit.get("ground_area_m2") or 0.0)
        gross = float(fit.get("gross_floor_area_m2") or 0.0)
        storeys = gross / ground if ground > 1e-6 else 0.0
        rows.append((storeys, gross, record["name"]))
    rows.sort(reverse=True)  # tall first - the under-served end leads

    variants: dict[str, int] = {}
    family_tag: dict[str, str] = {}
    if heroes:
        # One tile per sentence, its tallest variant standing for the rest.
        # 94% of the pool is coverage/siting re-tags, and rank order lays a
        # sentence's ~21 near-identical tags side by side - a browsing surface
        # that looks like duplication whatever the corpus holds. Grouping by
        # composition family also makes authoring convergence visible: same
        # family, adjacent tiles, no caption reading needed.
        from backend.app.modules.massing.workspace_tools.family_key import family_key  # noqa: E402
        best: dict[str, tuple[float, float, str]] = {}
        for storeys, gross, name in rows:
            sentence = name.split("~")[0].split("^")[0]
            variants[sentence] = variants.get(sentence, 0) + 1
            if sentence not in best:
                best[sentence] = (storeys, gross, name)
        for sentence in best:
            if sentence in book:
                opener, moves, stature = family_key(book[sentence])
                family_tag[sentence] = (
                    f"{opener}/{next(iter(moves), '-')}/{stature}")
        # One tile per FAMILY, not per sentence: three sentences that open
        # the same way and make the same dominant move are one idea, and
        # showing all three is how a sheet of nineteen came back reading as
        # six. The tallest stands for its family, which is the rule this
        # block's own docstring states.
        # One tile per family AND per source book. The family alone evicted
        # every reference edition: BIG delivers 350 variants over 14 families
        # and 11 of those families also hold sentences somebody else wrote, so
        # with the tallest variant winning the tile, BIG, OMA and SANAA came to
        # the sheet as one tile each and SANAA - low pavilions, always the
        # shorter of any pair - as none. A sheet whose point is to compare how
        # different authors solve the same figure cannot show one of them.
        origin: dict[str, str] = {}
        for path in sorted((ROOT / "inputs").glob("*.json")):
            try:
                schemes = json.loads(path.read_text(encoding="utf-8"))["schemes"]
            except Exception:  # noqa: BLE001 - a malformed book is skipped elsewhere
                continue
            for scheme in schemes:
                name = scheme.get("name")
                if name:
                    origin.setdefault(str(name), path.stem)
        best_of_family: dict[tuple, tuple] = {}
        for item in rows:
            sentence = item[2].split("~")[0].split("^")[0]
            scheme = book.get(sentence)
            if scheme is None:
                continue
            key = family_key(scheme) + (origin.get(sentence, "?"),)
            if key not in best_of_family or item[0] > best_of_family[key][0]:
                best_of_family[key] = item
        rows = sorted(
            best_of_family.values(),
            key=lambda item: (
                family_tag[item[2].split("~")[0].split("^")[0]], -item[0]))

    out = ROOT / "runs" / (out_name or f"pool-{run}")
    out.mkdir(parents=True, exist_ok=True)
    from backend.app.modules.massing.workspace_tools.vlm_shortlist import shape_id  # noqa: E402  (the jury's own identity)

    batch, sheet, drawn, failed, repeated = [], 0, 0, 0, 0
    seen_shapes: dict[str, str] = {}
    from backend.app.modules.massing.workspace_tools.solid_presentation import SolidPresentationRegistry
    solid_forms = SolidPresentationRegistry()
    suppressed: list[dict] = []
    seen_figures: dict[tuple, str] = {}
    drawings: list = []
    index = 0
    kept: list[dict] = []
    for storeys, gross, name in rows:
        family = name.split("~")[0].split("^")[0]
        parti = book.get(family)
        if parti is None:
            failed += 1
            continue
        asked = max((float(op.get("storeys") or 0) for op in parti["ops"]),
                    default=0.0)
        source = rebuild(name, book, site, buildable, axis,
                         max(base, asked * site.floor_height_m),
                         schedule=schedule)
        if source is None:
            failed += 1
            continue
        # The same building twice is not two alternatives. Coverage and siting
        # tags mostly redraw one mass, and the sheet was laying it out five
        # times in a row; the geometry's own identity is the honest test, so a
        # tag the envelope really does cut differently still earns its tile.
        identity = shape_id(source)
        if identity in seen_shapes:
            repeated += 1
            suppressed.append({'name': name, 'shape_id': identity,
                               'same_geometry_as': seen_shapes[identity]})
            continue
        form_comparison = solid_forms.find_or_add(name, source)
        if form_comparison.get('duplicate_of'):
            repeated += 1
            suppressed.append({'name': name, 'shape_id': identity,
                               'same_form_as': form_comparison['duplicate_of'],
                               'storeys': storeys, 'gross_m2': gross,
                               'comparison': form_comparison})
            continue
        # One tile per sentence and coverage band. Exact solid equality is the
        # right test for "the same mass" and the wrong one for "the same
        # picture": on comp17 it found nothing to merge among 203 tiles, while
        # five sentences took 95 of them - field_under_butterfly_wings alone
        # appeared 25 times, moved around the parcel. Siting slides a mass
        # across the site without changing what it is, so the browsing surface
        # keeps one of each. The band stays, because a scheme taking 35% of the
        # ground is a different proposal from the same scheme taking all of it,
        # and every dropped variant is written into `suppressed` with the tile
        # that stands for it - the choice is recorded, not destroyed, and the
        # board, the jury and the ledger never see this rule at all.
        band = name.split("~")[1].split("^")[0] if "~" in name else ""
        figure = (family, band)
        if figure in seen_figures:
            repeated += 1
            suppressed.append({'name': name, 'shape_id': identity,
                               'same_sentence_and_band_as': seen_figures[figure],
                               'storeys': storeys, 'gross_m2': gross})
            continue
        seen_figures[figure] = name
        # Similar ground plans may conceal different upper levels, roofs,
        # holes or siting cuts. Record the relation without deleting a choice.
        mark = _drawing_signature(source)
        similar_to = [other_name for other_name, seen in drawings
                      if mark is not None and _same_drawing(mark, seen)]
        if mark is not None:
            drawings.append((name, mark))
        seen_shapes[identity] = name
        index += 1
        drawn += 1
        kept.append({"rank": index, "storeys": round(storeys, 1), "name": name,
                     "shape_id": identity, "similar_plan_to": similar_to,
                     "solid_presentation": form_comparison})
        meta = {
            "층": f"{storeys:.1f}", "용적": f"{gross / parcel * 100:.0f}%",
            "": family[:24],
        }
        if heroes:
            meta["안"] = str(variants.get(family, 1))
            meta[""] = f"{family_tag.get(family, '?')[:20]} {family[:16]}"
        batch.append((f"#{index}", source, meta))
        if len(batch) == PER_SHEET:
            sheet += 1
            render_masses(batch, out / f"pool{sheet:03d}.png",
                          site_ring=list(buildable.exterior.coords),
                          columns=COLUMNS, tile=TILE, style="massing")
            print(f"pool{sheet:03d}.png  ({drawn}/{len(rows)})", flush=True)
            batch = []
    if batch:
        sheet += 1
        render_masses(batch, out / f"pool{sheet:03d}.png",
                      site_ring=list(buildable.exterior.coords),
                      columns=COLUMNS, tile=TILE, style="massing")
    (out / "pool-index.json").write_text(
        json.dumps(kept, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "pool-suppressed.json").write_text(
        json.dumps(suppressed, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"done: {drawn} distinct masses drawn, {repeated} repeats of a mass already "
          f"drawn skipped, {failed} rebuild-failed, {sheet} sheets -> {out}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main(*sys.argv[1:4]))
