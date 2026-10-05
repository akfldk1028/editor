"""Anonymous tiles for a blind round, and the key that says what they were.

A judge who can read `kahn_kimbell_three_ranges_of_vaults` off the drawing is
not judging the drawing. So each mass is rendered on its own with a number and
its own thesis sentence - what the scheme is for, which a jury does get - and
nothing that says which sentence wrote it, which run made it, or whether it is
old or new.

The key is written beside the tiles rather than into them, so a round can be
scored first and attributed afterwards. `runs/judge/prompts.json` holds the
rubric; do not edit it between rounds.

    python tools/judge_tiles.py <run> [count] [out-dir-name]
    python tools/judge_tiles.py uij-many 10 judge-0831
"""

from backend.app.modules.massing import paths as _mass_paths
from backend.app.modules.design.generation import paths as _design_paths
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime


import json
import hashlib
import random
import sys
from pathlib import Path

from backend.app.modules.massing.workspace_tools.band_probe import corpus, schedule_of  # noqa: E402  (django setup inside)
from backend.app.modules.massing.workspace_tools.finalists import PNU, rebuild, BUILDING_TYPE  # noqa: E402

from backend.app.modules.design.generation.maas.massv2.legal import load_legal_site  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.render import render_masses  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.siting import site_open_side_direction  # noqa: E402

ROOT = _mass_paths.workspace_root()


def allocate_stage(summary, count, fresh_sources, rebuild_source):
    """Reserve jury exposure, never a score, from the selector's accepted names.

    The callback retains the existing reconstruction gates and returns
    (source, refusal_reason). Missing historical input keeps the old ordering.
    """
    chosen = list(dict.fromkeys((summary.get('selection') or {}).get('chosen_names') or []))
    cell_of = {r['name']: r.get('cell') or '?' for r in summary['records']}
    order = list(chosen)
    random.Random(20260831).shuffle(order)
    by_cell = {}
    for name in order:
        by_cell.setdefault(cell_of.get(name, '?'), []).append(name)
    firsts = [names[0] for names in by_cell.values()]
    legacy = firsts + [name for name in order if name not in firsts]
    wanted = int(count)
    if wanted < 1:
        raise ValueError('stage count must be positive')
    evidence = {
        'schema': 'massv2.stage_selection.v1',
        'policy': 'legacy_cell_order' if fresh_sources is None else 'selected_source_and_cell_union',
        'requested_count': wanted, 'selector_chosen_names': chosen,
        'supplied_source_names': list(dict.fromkeys(fresh_sources or [])),
        'source_reservations': [], 'cell_representatives': [], 'refused': [],
        'fresh_sources_without_selected_variant': [], 'fresh_sources_without_rebuildable_variant': [],
    }
    cached, admitted = {}, {}

    def admit(name):
        if name not in cached:
            source, reason = rebuild_source(name)
            cached[name] = source
            if source is None:
                evidence['refused'].append({'name': name, 'reason': reason or 'rebuild returned no source'})
        if cached[name] is None:
            return False
        admitted[name] = cached[name]
        return True

    if fresh_sources is not None:
        for source_name in evidence['supplied_source_names']:
            variants = [name for name in chosen if name.split('~')[0].split('^')[0] == source_name]
            if not variants:
                evidence['fresh_sources_without_selected_variant'].append(source_name)
                continue
            for name in variants:  # selector order, not random priority within a source
                if admit(name):
                    evidence['source_reservations'].append({'source': source_name, 'name': name})
                    break
            else:
                evidence['fresh_sources_without_rebuildable_variant'].append(source_name)
        # Keep the existing cell representatives even if a source reserve has
        # that cell already. A coarse cell does not prove geometric equivalence.
        for cell, names in by_cell.items():
            for name in names:
                if admit(name):
                    evidence['cell_representatives'].append({'cell': cell, 'name': name})
                    break
    minimum = len(admitted)
    for name in legacy:
        if len(admitted) >= max(wanted, minimum):
            break
        admit(name)
    # Seeded presentation order hides membership priority; historical order is
    # unchanged when no canonical author input is available.
    names = [name for name in legacy if name in admitted]
    evidence.update(minimum_breadth_count=minimum, admitted_count=len(names), admitted_names=names,
                    overflow_count=max(0, len(names) - wanted),
                    attempted_names=list(cached),
                    selected_not_admitted=[name for name in chosen if name not in admitted])
    return [(name, admitted[name]) for name in names], evidence


def main(run: str, count: str = "10", out_name: str = "") -> int:
    summary_path = ROOT / 'runs' / run / 'massv2-summary.json'
    summary_raw = summary_path.read_bytes()
    summary = json.loads(summary_raw)
    book = corpus()
    schedule = schedule_of(run)
    site = load_legal_site(PNU, building_type=BUILDING_TYPE)
    buildable = site.plan_at(0.0)
    axis = site_open_side_direction(site) or (1.0, 0.0)
    base = site.floor_height_m * max(
        1, int(site.far_capacity_m2 // max(1.0, site.ground_capacity_m2)))
    parcel = float(summary["site"]["parcel_area_m2"])

    input_path = ROOT / 'inputs' / f'gen-{run}.json'
    fresh_sources, input_evidence = None, {'path': str(input_path), 'status': 'unavailable'}
    if input_path.is_file():
        raw = input_path.read_bytes()
        payload = json.loads(raw)
        fresh_sources = [row['name'] for row in payload['schemes']]
        input_evidence.update(status='available', sha256=hashlib.sha256(raw).hexdigest())

    def resolve(name):
        family = name.split('~')[0].split('^')[0]
        if book.get(family) is None:
            return None, 'selected source absent from current corpus'
        source = rebuild(name, book, site, buildable, axis, base, schedule=schedule)
        return source, None if source is not None else 'existing rebuild gates returned no source'

    seats, selection = allocate_stage(summary, count, fresh_sources, resolve)
    selection.update(author_input=input_evidence,
                     selector_summary={'path': str(summary_path), 'sha256': hashlib.sha256(summary_raw).hexdigest()},
                     rendered_names=[])

    out = ROOT / "runs" / (out_name or f"judge-{run}")
    out.mkdir(parents=True, exist_ok=True)
    selection_path = out / 'stage-selection.json'
    selection_path.write_text(json.dumps(selection, ensure_ascii=False, indent=2), encoding='utf-8')
    key = []
    made = 0
    for name, source in seats:
        family = name.split("~")[0].split("^")[0]
        parti = book[family]
        record = next((r for r in summary["records"] if r["name"] == name), None)
        fit = (record or {}).get("legal_fit") or {}
        ground = float(fit.get("ground_area_m2") or 0.0)
        gross = float(fit.get("gross_floor_area_m2") or 0.0)
        made += 1
        tile = f"t{made:02d}"
        render_masses(
            [(tile, source, {
                # The thesis, because a jury is told what an option is for. The
                # sentence's own name is not, because that is the answer sheet.
                "thesis": str(parti.get("formal_principle") or "")[:180],
                "건폐율": f"{ground / parcel * 100:.0f}%",
                "용적률": f"{gross / parcel * 100:.0f}%",
            })],
            out / f"{tile}.png", site_ring=list(buildable.exterior.coords),
            columns=1, tile=(900, 820), style="massing",
        )
        key.append({"tile": tile, "run": run, "name": name,
                    "cell": (record or {}).get("cell"),
                    "coverage_pct": round(ground / parcel * 100, 1),
                    "storeys": round(gross / max(ground, 1e-9), 1)})
        selection['rendered_names'].append(name)
        selection_path.write_text(json.dumps(selection, ensure_ascii=False, indent=2), encoding='utf-8')

    # The rubric travels with the round it judged.
    (out / "prompts.json").write_text(
        (ROOT / "inputs" / "judge-prompts.json").read_text(encoding="utf-8"),
        encoding="utf-8")
    (out / "key.json").write_text(
        json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{made} tiles -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:4]))
