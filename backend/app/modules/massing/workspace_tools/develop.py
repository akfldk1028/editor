"""The development loop: grow a chosen sentence instead of breeding new ones.

OMA makes a hundred and fifty models and then develops ONE through dozens of
passes; this pipeline only ever generated. The visible cost was measured all
week - first-legal-fit partis that read as diagrams next to the offices'
tuned models. This tool is the missing half: take a board winner, mutate its
OWN sentence locally (proportions, extremity, FAR attainment), deliver every
mutant down the same legal path, and stage parent-vs-mutant pairs for blind
pairwise judging - keep the child only when a judge prefers it.

Without a payload, deterministic mutants vary by index. An authored payload
provides complete child records bound to the exact scored parent instead.

    python tools/develop.py <run> <variant-name> [count]
    python tools/develop.py <run> <variant-name> <count> --authored-payload <json>
      -> runs/develop-<family>/ : mutant tiles + pairs/ + mutants.json
"""

from backend.app.modules.massing import paths as _mass_paths
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime


from backend.app.modules.design.generation import paths as _design_paths

import copy
import hashlib
import json
import re
import sys
from pathlib import Path

from backend.app.modules.massing.workspace_tools.band_probe import corpus, schedule_of  # noqa: E402
from backend.app.modules.massing.workspace_tools.finalists import PNU, rebuild, BUILDING_TYPE  # noqa: E402

from backend.app.modules.design.generation.maas.massv2.legal import load_legal_site  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.render import render_masses  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.siting import site_open_side_direction  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.delivery_gate import assess_delivery
from backend.app.modules.design.generation.maas.massv2.grammar import declared_stature

ROOT = _mass_paths.workspace_root()

# What development is allowed to touch, and how far. Caps mirror the
# vocabulary's own clamps - a mutant that leaves the language is not a
# development, it is a different sentence.
TUNABLE = {
    "pitch": (0.15, 1.2), "rise": (0.15, 1.2), "reach": (0.1, 0.45),
    "proud": (0.1, 1.0), "turn": (-60.0, 60.0), "height": (0.05, 1.0),
    "bar": (0.15, 0.4), "size": (0.15, 0.6), "ratio": (0.2, 0.8),
    "clearance": (0.1, 0.6), "at": (0.0, 1.0), "contrast": (1.0, 2.0),
    "spread": (1.0, 2.4), "over": (0.05, 0.6), "bite": (0.3, 0.75),
    "depth": (0.1, 0.5),
}
STEPS = (-0.30, -0.15, 0.15, 0.30)  # proportional nudges
FAR_FILL_STOREYS = (4, 5, 6, 7)     # the client axis: fill the volume


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))


def mutants_of(scheme: dict, count: int) -> list[dict]:
    """Local variations of one sentence, deterministic, in-language."""

    sites = []  # (op_index, param, base_value)
    for oi, op in enumerate(scheme["ops"]):
        for param, bounds in TUNABLE.items():
            if param in op and isinstance(op[param], (int, float)):
                sites.append((oi, param, float(op[param]), bounds))
    out = []
    serial = 0
    # 1) proportional nudges across every tunable site
    for oi, param, base_value, (lo, hi) in sites:
        for step in STEPS:
            if len(out) >= count:
                return out
            child = copy.deepcopy(scheme)
            child["ops"][oi][param] = round(_clamp(
                base_value * (1.0 + step) if param != "turn"
                else base_value + 60.0 * step, lo, hi), 3)
            serial += 1
            child["name"] = f"{scheme['name']}__d{serial:02d}_{param}{'+' if step > 0 else '-'}"
            out.append(child)
    # 2) extremize: push each site to its cap (the BIG rule - lukewarm
    #    parameters read as leftovers)
    for oi, param, base_value, (lo, hi) in sites:
        if len(out) >= count:
            return out
        child = copy.deepcopy(scheme)
        cap = hi if base_value >= (lo + hi) / 2 else lo
        child["ops"][oi][param] = cap
        serial += 1
        child["name"] = f"{scheme['name']}__d{serial:02d}_{param}cap"
        out.append(child)
    # 3) FAR attainment: the client wants the volume filled - say more storeys
    for storeys in FAR_FILL_STOREYS:
        if len(out) >= count:
            return out
        child = copy.deepcopy(scheme)
        opener = child["ops"][0]
        if float(opener.get("storeys") or 0) == storeys:
            continue
        opener["storeys"] = storeys
        opener["height"] = round(_clamp(
            float(opener.get("height") or 0.5) * storeys
            / max(1.0, float(opener.get("storeys") or 3)), 0.1, 1.0), 3)
        serial += 1
        child["name"] = f"{scheme['name']}__d{serial:02d}_far{storeys}f"
        out.append(child)
    return out


def _read_authored_payload(path, *, parent, count, expected_shape_id=None):
    """Validate an exact, parent-bound author response before touching outputs."""
    from backend.app.modules.design.generation.maas.massv2.grammar import PLOT_MODES, parti_from_record

    path = Path(path).resolve()
    raw = path.read_bytes()
    payload = json.loads(raw.decode('utf-8'))
    parent_variants = {parent, parent.split('^')[0], f"{parent.split('^')[0]}^centred"}
    if not isinstance(payload, dict) or payload.get('parent') not in parent_variants:
        raise ValueError('authored development payload must name the exact parent variant')
    bound = payload.get('parent_shape_id')
    if not isinstance(bound, str) or not bound or (expected_shape_id and bound != expected_shape_id):
        raise ValueError('authored development payload parent_shape_id differs from the scored parent')
    children = payload.get('schemes')
    if int(count) <= 0 or not isinstance(children, list) or len(children) != int(count):
        raise ValueError(f'authored development requires exactly {count} schemes')
    names = set()
    family = parent.split('~')[0].split('^')[0]
    for child in children:
        if not isinstance(child, dict):
            raise ValueError('each authored child must be a full scheme record')
        name = child.get('name')
        if (not isinstance(name, str) or not name.strip() or name != name.strip()
                or any(marker in name for marker in ('~', '^')) or name.startswith('book:')
                or name == family or name in names):
            raise ValueError('authored child names must be unique base names distinct from the parent')
        names.add(name)
        ops = child.get('ops')
        if (not isinstance(ops, list) or not ops or any(
                not isinstance(op, dict) or not isinstance(op.get('op'), str)
                or op.get('op') not in PLOT_MODES for op in ops)
                or parti_from_record(child) is None):
            raise ValueError(f'{name}: invalid authored operations; unknown verbs cannot be dropped')
    return payload, {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()}


def main(run: str, variant: str, count: str = "24", output_dir=None,
         expected_shape_id=None, authored_payload=None) -> int:
    authored, author_evidence = (None, None)
    if authored_payload is not None:
        authored, author_evidence = _read_authored_payload(
            authored_payload, parent=variant, count=count, expected_shape_id=expected_shape_id)
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

    family = variant.split("~")[0].split("^")[0]
    parent_scheme = book[family]
    out = Path(output_dir) if output_dir else ROOT / "runs" / f"develop-{family[:28]}"
    if authored and any(child['name'] in book for child in authored['schemes']):
        raise ValueError('authored child name already exists in the corpus; use a new name')

    delivery_diagnostics = {}

    def deliver(scheme, name_for_pipeline):
        local_book = dict(book)
        local_book[scheme["name"].split("~")[0].split("^")[0]] = scheme
        details = {}
        source = rebuild(name_for_pipeline, local_book, site, buildable, axis,
                         base, schedule=schedule, diagnostics=details)
        delivery_diagnostics[name_for_pipeline] = details
        return source

    parent_source = deliver(parent_scheme, variant)
    if parent_source is None:
        print("parent rebuild failed"); return 1
    from backend.app.modules.massing.workspace_tools.vlm_shortlist import shape_id
    if expected_shape_id and shape_id(parent_source) != expected_shape_id:
        print("parent shape differs from scored board identity; re-stage and rejudge first")
        return 1
    if authored and shape_id(parent_source) != authored['parent_shape_id']:
        print('parent shape differs from authored payload binding; reauthor for the current parent')
        return 1

    # Execute every authored record before output cleanup as well. Nested shape
    # payload errors are owned by the executor, and must not erase an old stage.
    children = authored['schemes'] if authored else mutants_of(parent_scheme, int(count))
    prepared = []
    for child in children:
        child_variant = child['name'] + variant[len(family):]
        prepared.append((child, child_variant, deliver(child, child_variant)))

    (out / "pairs").mkdir(parents=True, exist_ok=True)
    for stale in (out / "pairs").glob("p*.png"):
        stale.unlink()

    def delivered_shape(source):
        # Share the jury geometry identity, including holes and surface functions.
        return shape_id(source)

    ledger = []
    kept = 0
    erased = 0
    seen_shapes = {delivered_shape(parent_source)}
    for child, child_variant, child_source in prepared:
        child_family = child["name"]
        # the mutant keeps the parent's variant suffixes (siting/coverage)
        child_record = {'name': child_family, 'scheme': child, 'variant': child_variant}
        if child_source is None:
            details = delivery_diagnostics.get(child_variant) or {}
            gap = details.get('gap')
            ledger.append({**child_record, "delivered": False,
                           'eligibility': {'accepted': False,
                               'reasons': ['declared_gap_closed'] if gap and not gap['satisfied']
                                          else ['legal_fit_or_compile_failed'], **details}})
            continue
        shape = delivered_shape(child_source)
        if shape in seen_shapes:
            # Asked for something else and got this again: the mutation was
            # inside what the growth loop normalises, so there is nothing to
            # judge.
            erased += 1
            ledger.append({**child_record, "delivered": True,
                           "erased_by_delivery": True})
            continue
        eligibility = assess_delivery(child_source, site,
            storey_m=float(child.get('floor_height_m') or site.floor_height_m),
            declaration={**child_source.metadata, **declared_stature(child)},
            parcel_area_m2=parcel)
        if not eligibility.accepted:
            ledger.append({**child_record, 'delivered': True, 'shape_id': shape,
                           'eligibility': eligibility.evidence()})
            continue
        seen_shapes.add(shape)
        kept += 1
        pair = out / "pairs" / f"p{kept:02d}.png"
        render_masses(
            [("A", parent_source, {}), ("B", child_source, {})],
            pair, site_ring=list(buildable.exterior.coords),
            columns=2, tile=(620, 560), style="massing")
        from backend.app.modules.massing.workspace_tools.presentation import append_jury_drawings
        drawings = append_jury_drawings(pair, [
            (variant, parent_source, parent_scheme.get('floor_height_m') or site.floor_height_m),
            (child['name'], child_source, child.get('floor_height_m') or site.floor_height_m)], buildable)
        ledger.append({**child_record, "delivered": True,
                       "pair": pair.name, "shape_id": shape_id(child_source),
                       'eligibility': eligibility.evidence(), 'jury_drawings': drawings})
    (out / "mutants.json").write_text(
        json.dumps({"parent": variant, "parent_scheme": parent_scheme,
                    "parent_shape_id": shape_id(parent_source), "run": run,
                    'author_mode': 'payload' if authored else 'deterministic',
                    'authored_payload': author_evidence,
                    "children": ledger},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{kept} delivered mutants, pairs -> {out / 'pairs'}")
    if erased:
        print(f"{erased} mutants arrived as a building already staged - the "
              "growth loop normalised the change away; not offered as a choice")
    print("next: blind pairwise judges pick A or B per pair; "
          "keep B only where preferred; repeat on the winner.")
    return 0


def _mutation_serial(name: str) -> int:
    """The mutation's own serial, read off the name mutants_of gave it."""

    hit = re.search(r"__d(\d+)_", name)
    return int(hit.group(1)) if hit else 10 ** 6


def _mutation_change(parent: dict, child: dict) -> str:
    """What the mutation moved, read off the two dicts rather than the name.

    The name says `bar+`; the brief has to say which op and by how much, or
    the next author cannot avoid re-proposing the parent's value.
    """

    moves = []
    for index, after in enumerate(child['ops']):
        before = parent['ops'][index] if index < len(parent['ops']) else {}
        for key, value in after.items():
            if key != "why" and before.get(key) != value:
                moves.append(f"ops[{index}].{key} {before.get(key)} -> {value}")
    for index in range(len(child['ops']), len(parent['ops'])):
        moves.append(f"ops[{index}] removed: {parent['ops'][index].get('op')}")
    return ", ".join(moves) or "no parameter moved"


def _champion_pair(record: dict) -> tuple[dict, dict] | None:
    """The parent sentence and the champion's own, as dicts.

    The champion is the parent with one mutation applied, and mutants_of
    already builds exactly that dict deterministically - so the winner is
    regenerated from the parent by name rather than re-derived here. A second
    derivation of the same thing is the hand-copy the one-owner rule exists
    to stop; the extract gap parameter was written twice in two coordinate
    systems that way.
    """

    family = str(record["parent"]).split("~")[0].split("^")[0]
    parent = record.get("parent_scheme") or corpus().get(family)
    if parent is None:
        return None
    for row in record["children"]:
        if row["name"] == record["champion"] and row.get("scheme"):
            return parent, row["scheme"]
    for child in mutants_of(parent, len(record["children"])):
        if child["name"] == record["champion"]:
            return parent, child
    return None


def _with_developed_why(parent: dict, child: dict) -> dict:
    """The champion's prose says what its value now is.

    The champion is the parent with one parameter moved, and it carried the
    parent's `why` unchanged - so a sentence that said "a 3 m gap so the
    court reads as a court" shipped with gap 4.5, and the next author read
    the argument for a value the mass no longer has. The moved op's why now
    ends with the move and how it was decided.
    """

    ops = []
    for index, after in enumerate(child["ops"]):
        before = parent['ops'][index] if index < len(parent['ops']) else {}
        after = dict(after)
        moves = [f"{key} {before.get(key)} -> {value}"
                 for key, value in after.items()
                 if key != "why" and before.get(key) != value]
        if moves:
            why = str(after.get("why") or "").rstrip(". ")
            after["why"] = (f"{why}. Developed: {', '.join(moves)}, "
                            f"chosen over the parent by a unanimous blind pairwise jury.")
        ops.append(after)
    return {**child, "ops": ops}


def _seat_in_corpus(scheme: dict) -> str:
    """Append the winning sentence to the authored corpus.

    champion.json was written and then read by nothing: a development that
    beat its parent in front of a jury reached neither the corpus, nor the
    board, nor the next author, so the only real result a development round
    produces evaporated when the round ended. A run delivers what the books
    hold, so the champion belongs in a book.
    """

    path = ROOT / "inputs" / "gen-develop.json"
    book = (json.loads(path.read_text(encoding="utf-8"))
            if path.exists() else {"schemes": []})
    if any(seated.get("name") == scheme["name"] for seated in book["schemes"]):
        return f"already in {path.name}: {scheme['name']}"
    book["schemes"].append(scheme)
    path.write_text(json.dumps(book, ensure_ascii=False, indent=1) + '\n',
                    encoding="utf-8")
    return f"seated in {path.name}: {scheme['name']}"


def _read_pair_ballots(paths, expected):
    if len(paths) != 3 or len({Path(p).resolve() for p in paths}) != 3 or not expected:
        raise ValueError("three distinct ballots and at least one pair are required")
    votes = {pair: [] for pair in expected}
    for path in paths:
        rows = re.findall(r"^PAIR\s+(p\d+):\s*([AB])\b",
                          Path(path).read_text(encoding="utf-8"), re.M)
        if len(rows) != len(expected) or {p for p, _ in rows} != expected:
            raise ValueError(f"incomplete, duplicate or unknown pair ballot: {path}")
        for pair, choice in rows:
            votes[pair].append(choice)
    return votes


def score(family_dir: str, verdict_paths: list[str]) -> int:
    """Aggregate blind pairwise verdicts; a child wins only unanimously.

    Ties and splits go to the parent - the incumbent rule, because a
    development step that cannot convince every judge is not an improvement,
    it is drift. Writes champion.json naming the winning child - the one the
    most jurors voted for - and seats that child's sentence in the corpus so
    the next run can deliver it.
    """

    out = ROOT / "runs" / family_dir
    record = json.loads((out / "mutants.json").read_text(encoding="utf-8"))
    jurors = len(verdict_paths)
    expected = {Path(c["pair"]).stem for c in record["children"] if c.get("pair")}
    try:
        votes = _read_pair_ballots(verdict_paths, expected)
    except (OSError, ValueError) as exc:
        print(f"REFUSED: {exc}")
        return 1
    winners: list[tuple[int, int, str]] = []
    for child in record["children"]:
        if not child.get("delivered"):
            continue
        # A mutant that arrived as a building already staged has no pair and
        # no vote: the growth loop normalised its change away, so there was
        # nothing for a judge to choose between. It stays in the ledger as
        # the measurement of that, and is not counted as a loss.
        if not child.get("pair"):
            child["votes"] = ""
            continue
        pair = child["pair"].removesuffix(".png")
        cast = votes.get(pair, [])
        # Unanimity has to mean every juror who was handed a sheet, not every
        # vote that happened to arrive: one verdict file saying B used to read
        # as a consensus, which is how a single opinion could rewrite the
        # corpus. Requiring one vote per file makes a one-juror round look
        # like a one-juror round, and champion.json records the count.
        if cast and len(cast) >= jurors and all(vote == "B" for vote in cast):
            winners.append((len(cast), _mutation_serial(child["name"]),
                            child["name"]))
        child["votes"] = "".join(cast)
    # The docstring promised the most decisive support and the code took
    # whichever child the ledger happened to list first - which is mutation
    # order, not jury order. Sort by how many jurors voted the pair, then by
    # the mutation serial so a tie goes to the smaller, earlier change: the
    # nearer development is the one the parent's virtues survive.
    winners.sort(key=lambda row: (-row[0], row[1]))
    names = [name for _, _, name in winners]
    record["unanimous_children"] = names
    record["champion"] = names[0] if names else None
    record["jurors"] = jurors
    seated = ""
    if record["champion"]:
        pair = _champion_pair(record)
        if pair is None:
            print(f"REFUSED: champion {record['champion']} cannot resolve its authored parent")
            return 1
        else:
            parent_scheme, champion_scheme = pair
            record["champion_change"] = _mutation_change(parent_scheme,
                                                         champion_scheme)
            seated = _seat_in_corpus(_with_developed_why(parent_scheme, champion_scheme))
    else:
        family = str(record["parent"]).split("~")[0].split("^")[0]
        parent_scheme = record.get("parent_scheme") or corpus().get(family)
        if parent_scheme is None:
            print("REFUSED: retained parent cannot be fed into the next corpus")
            return 1
        seated = _seat_in_corpus(parent_scheme)
    record["feedback_written"] = True
    (out / "champion.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"pairs judged {len(votes)}, jurors {jurors}, "
          f"unanimous child wins {len(names)}")
    for name in names:
        print("  WIN", name.split("__")[-1])
    print("champion:", record["champion"] or "parent holds (no unanimous win)")
    if seated:
        print(seated)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if "--score" in sys.argv:
        i = sys.argv.index("--score")
        sys.exit(score(sys.argv[1], sys.argv[i + 1:]))
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run')
    parser.add_argument('variant')
    parser.add_argument('count', nargs='?', default='24')
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--expected-shape-id')
    parser.add_argument('--authored-payload', type=Path)
    args = parser.parse_args()
    sys.exit(main(args.run, args.variant, args.count, output_dir=args.output_dir,
                  expected_shape_id=args.expected_shape_id, authored_payload=args.authored_payload))
