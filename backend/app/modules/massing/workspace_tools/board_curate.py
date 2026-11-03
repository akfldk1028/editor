"""The selection board, assembled from the ledgers instead of by hand.

The board was curated manually three times in one evening, and each time a
family of near-identical partis slipped through in a different way. This
tool owns the whole path now: it collects every juried result (both tracks,
every round), computes each passer's composition family from its sentence,
keeps the best-scored member per family per track, and emits the board key.
Rendering and publishing read that key; nobody picks tiles by eye again.

    python tools/board_curate.py          # writes runs/board/board-key.json + ledger
"""

from backend.app.modules.massing import paths as _mass_paths
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime


from backend.app.modules.design.generation import paths as _design_paths

import json
import os
import sys
from copy import deepcopy
from pathlib import Path

from backend.app.modules.massing.workspace_tools.evaluation_contract import active_rubrics, compatible
from backend.app.modules.massing.workspace_tools.family_key import family_key, one_per_family  # noqa: E402

ROOT = _mass_paths.workspace_root()

# Every juried round, its track, and where its scores live. Anchor entries
# re-judged in later rounds keep their latest score (rounds listed newest
# last override).
ROUNDS = [
    ("K", "runs/judge-24/final-ranking.json", "final"),
    ("O", "runs/judge-ovs/vlm-shortlist.json", "shortlist"),
    ("O", "runs/judge-void-ovs/vlm-shortlist.json", "shortlist"),
    ("K", "runs/judge-void-kor/vlm-shortlist.json", "shortlist"),
    ("O", "runs/judge-refix/vlm-shortlist.json", "corrected"),
    ("O", "runs/judge-ovs2/vlm-shortlist.json", "shortlist"),
    ("O", "runs/vlm-ovs9-family/vlm-shortlist.json", "shortlist"),
    ("O", "runs/vlm-ovs10-new/vlm-shortlist.json", "shortlist"),
    # Rule 0's corollary: the smooth-curve renderer changed the drawings, so
    # the seated overseas entries were re-judged on the rebaked tiles under
    # the track's own rubric. Newest-last, so these scores override.
    ("O", "runs/vlm-board-rejudge-1/vlm-shortlist.json", "corrected"),
    # The partial correction above re-judged only the SEATED entries, and
    # curation then compared its new-rubric scores against merged-out
    # partners still holding old-rubric numbers - two scales, one contest,
    # and the board flipped. One ruler over the whole passing ledger:
    ("O", "runs/vlm-o-full-rejudge/vlm-shortlist.json", "corrected"),
    ("O", "runs/vlm-ovs11-new/vlm-shortlist.json", "shortlist"),
    # First anchor-corrected round: three seated entries rode anonymously and
    # --score removed the session's measured -0.36 drift before recording.
    ("O", "runs/vlm-ovs14-r2/vlm-shortlist.json", "shortlist"),
    # First English-authored round (the prompt-language probe): same brief,
    # instructions and whys in English. Anchor-corrected like every round.
    ("O", "runs/vlm-ovs15-en/vlm-shortlist.json", "shortlist"),
    # Roof-section round: the client said the gables were gone; these
    # win their seats through the jury instead of squatting in a canon row.
    ("O", "runs/vlm-ovs16-en/vlm-shortlist.json", "shortlist"),
    # Pilotis + wide-slab round (closed-loop r2): the lifted court ring
    # and the punched mat, seats won by jury after the canon row left.
    ("O", "runs/vlm-ovs17-en/vlm-shortlist.json", "shortlist"),
    # The first round authored, revised and juried by massagent itself -
    # three independent juror processes, anchor-corrected (drift -1.02).
    ("O", "runs/vlm-agent01/vlm-shortlist.json", "shortlist"),
    # agent02: authored, sheet-diagnosed and revised (r2) by massagent,
    # judged by the pinned sonnet jury under the no-shift rule.
    ("O", "runs/vlm-agent02/vlm-shortlist.json", "shortlist"),
    # sweep01: the first grammar-sweep round - 300 generated sentences,
    # 5,132 variants, first-ever 16/16 cell fill; jury drift -0.48 applied.
    ("O", "runs/vlm-sweep01/vlm-shortlist.json", "shortlist"),
    # 09-02 surgery day: executor, gates and renderer changed (height budget,
    # roof-on-top-tier, crumb width, shift span, fracture lean, ridge
    # vectors, structure-per-part). One ruler: the whole passing overseas
    # ledger re-judged on the final engine, then the first authored round
    # written against the empty-family map on that engine.
    ("O", "runs/vlm-board-rejudge-s7/vlm-shortlist.json", "corrected"),
    ("O", "runs/vlm-ovs18-en/vlm-shortlist.json", "shortlist"),
    # First book-stack round on the massv2 stage: c250-t3's six exact
    # GeometryProgram masses at their own size and height, three board
    # anchors riding. Seats resolve through runs/books/ (book_import).
    ("O", "runs/vlm-book02/vlm-shortlist.json", "shortlist"),
    # The ruler itself changed: every overseas round from 09-01 had been
    # judged on a Korean-weighted copy (Feasibility 0.35 / Aesthetics 0.15)
    # while the international rubric (CONCEPT 0.35) had no reader. One
    # ruler: the whole passing overseas ledger re-judged under the real
    # international rubric, newest-last so it overrides every score above.
    ("O", "runs/vlm-board-rejudge-intl/vlm-shortlist.json", "corrected"),
]
# The anchor-corrected pass thresholds recorded per round live in the
# shortlists as `pass`; the korea final ranking predates that format.
from backend.app.modules.massing.workspace_tools.vlm_shortlist import PASS_CUT, certificate_digest  # noqa: E402
KOREA_FINAL_PASS = PASS_CUT  # the one cut; this name survives for the pre-`pass` korea file


def rounds() -> list:
    """Every round the board reads: the legacy hand list, then every scored
    round that wrote a manifest (runs/vlm-*/round.json) and is not already
    listed, in the order their shortlists were scored. Newest last, so the
    latest ruler overrides."""

    # An era: runs/board/era.json (written by `--new-era`) names the moment
    # the board was cleared. Before it, nothing is read - not the hand list,
    # not older manifests. The old board is archived beside it, never lost.
    era = ROOT / "runs" / "board" / "era.json"
    active = active_rubrics(ROOT)
    since = float(json.loads(era.read_text(encoding="utf-8"))["since"]) if era.exists() else None
    listed = {rel for _t, rel, _k in ROUNDS}
    discovered = []
    for manifest in ROOT.glob("runs/vlm-*/round.json"):
        rel = str(manifest.parent.relative_to(ROOT) / "vlm-shortlist.json").replace("\\", "/")
        shortlist = manifest.parent / "vlm-shortlist.json"
        if (not active and since is None and rel in listed) or not shortlist.exists():
            continue
        stamp = shortlist.stat().st_mtime
        if since is not None and stamp < since:
            continue
        meta = json.loads(manifest.read_text(encoding="utf-8"))
        if active and not compatible(meta, active.get(meta["track"])):
            continue
        discovered.append((stamp, (meta["track"], rel, meta["kind"])))
    legacy = [] if since is not None or active else list(ROUNDS)
    return legacy + [entry for _stamp, entry in sorted(discovered)]


def new_era(note: str) -> None:
    """Clear the board: archive runs/board, then write era.json so only rounds
    scored from now on are read. The archive keeps every ledger and eye pass."""

    import shutil
    import time
    board = ROOT / "runs" / "board"
    stamp = time.strftime("%Y%m%d-%H%M")
    if board.exists():
        archive = ROOT / "runs" / f"board-archive-{stamp}"
        shutil.copytree(board, archive)
        for item in board.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
        print(f"archived the old board to {archive.relative_to(ROOT)}")
    board.mkdir(parents=True, exist_ok=True)
    (board / "era.json").write_text(json.dumps(
        {"since": time.time(), "started": stamp, "note": note}, indent=1, ensure_ascii=False),
        encoding="utf-8")
    print(f"new era from {stamp}: {note}")


def corpus() -> dict:
    book = {}
    # Sweep books live outside inputs/ so the authored canon stays clean,
    # but their sentences must still resolve once staged or juried.
    paths = sorted((ROOT / "inputs").glob("gen-*.json")) +         sorted((ROOT / "runs" / "sweeps").glob("*.json"))
    for path in paths:
        # A book the agent is mid-edit (or a probe someone half-wrote) must
        # not take every tool down with it: warn and skip, the way the
        # validator would refuse it.
        try:
            schemes = json.loads(path.read_text(encoding="utf-8"))["schemes"]
            if not all(isinstance(item, dict) and item.get("name") for item in schemes):
                raise ValueError("schemes must be records with names")
        except Exception as exc:  # noqa: BLE001
            import sys as _sys
            print(f"corpus: skipping {path.name} ({type(exc).__name__}: {exc})", file=_sys.stderr)
            continue
        for scheme in schemes:
            book[scheme["name"]] = scheme
    # Book-stack masses (book_language pipeline) staged through
    # book_import: each is its own family in its own layer - a 70-principle
    # vocabulary does not partition the way massv2's family key does, and
    # the six records are six designs. The registry is the owner.
    from backend.app.modules.massing.workspace_tools.book_import import registry as book_registry  # noqa: E402
    for name, entry in book_registry().items():
        book[name] = {"name": name, "layer": "book",
                      "formal_principle": entry.get("thesis", ""),
                      "ops": [{"op": verb} for verb in entry.get("verbs") or []]}
    return book


def exact_presentation_aliases(rows: list[dict], *, root: Path | None = None) -> list[dict]:
    """One presentation seat for verified exact aliases in one judging context.

    Certificate IDs bind names, so compare their complete evidence excluding
    only name and that ID. Never infer equivalence from a plan or family.
    Missing, ambiguous or malformed public evidence leaves the row separate.
    Input/ledger rows and each original score remain untouched.
    """
    import hashlib
    import math

    root = ROOT if root is None else root
    contexts: dict = {}
    numeric = ('ground_m2', 'gross_m2', 'storey_m', 'coverage_pct', 'far_pct', 'height_m')

    def evidence(row):
        if any(not isinstance(row.get(k), str) or not row[k]
               for k in ('track', 'round', 'name', 'shape_id', 'certificate_id')):
            return None
        context = row['round']
        if Path(context).name != context or context in ('.', '..'):
            return None
        if context not in contexts:
            path = root / 'runs' / context / 'key.json'
            try:
                raw = path.read_bytes()
                entries = json.loads(raw)
                if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
                    raise ValueError('public key must be a row list')
                contexts[context] = (entries, str(path), hashlib.sha256(raw).hexdigest())
            except (OSError, ValueError):
                contexts[context] = ([], str(path), None)
        entries, path, digest = contexts[context]
        matches = [e for e in entries if e.get('name') == row['name']]
        if len(matches) != 1:
            return None
        entry = matches[0]
        cert = entry.get('certificate')
        if not isinstance(cert, dict):
            return None
        if any(cert.get(k) != row[k] for k in ('name', 'shape_id', 'certificate_id')):
            return None
        if entry.get('shape_id') != row['shape_id'] or (
                'certificate_id' in entry and entry['certificate_id'] != row['certificate_id']):
            return None
        if any(type(cert.get(k)) not in (int, float) or not math.isfinite(cert[k]) for k in numeric):
            return None
        if any(not isinstance(cert.get(k), dict) or not cert[k]
               for k in ('storey_limit', 'area_limits', 'structure')):
            return None
        if not cert.get('site_pnu') or not cert.get('floor_area_basis'):
            return None
        if row['name'].startswith('book:') and not isinstance(cert.get('delivered_floor_evidence'), dict):
            return None
        try:
            if certificate_digest(cert) != row['certificate_id']:
                return None
            equivalent = json.dumps({k: v for k, v in cert.items()
                                     if k not in ('name', 'certificate_id')},
                                    sort_keys=True, allow_nan=False)
        except (TypeError, ValueError):
            return None
        return ((row.get('rubric_id'), row['track'], context, row['shape_id'], equivalent),
                dict(public_key=deepcopy(entry), public_key_path=path, public_key_sha256=digest))

    # Existing curator ranking: descending score, stable order for ties.
    chosen, representatives = [], {}
    for row in sorted(rows, key=lambda item: item['score'], reverse=True):
        verified = evidence(row)
        if verified is not None and verified[0] in representatives:
            representatives[verified[0]].setdefault('exact_geometry_aliases', []).append(
                dict(row=deepcopy(row), **verified[1]))
            continue
        seat = deepcopy(row)
        chosen.append(seat)
        if verified is not None:
            representatives[verified[0]] = seat
    return chosen


def main() -> int:
    import sys as _sys
    if len(_sys.argv) > 1 and _sys.argv[1] == "--new-era":
        note = " ".join(_sys.argv[2:]).strip()
        if not note:
            # Silently curating instead of clearing is the worst possible
            # answer here: the operator reads a normal board and believes the
            # era began.
            print("usage: board_curate.py --new-era <why this era begins>")
            return 2
        new_era(note)
        return 0
    book = corpus()
    book_only = os.environ.get('BOOK_ONLY') == '1'
    active = active_rubrics(ROOT)
    ledger: dict[tuple, dict] = {}
    for track, rel, kind in rounds():
        path = ROOT / rel
        if not path.exists():
            continue
        # Anchors ride a round to calibrate it; they are not re-contested by
        # it. Recording their ride-corrected scores let the ruler measure
        # itself - anchor spread compressed 23-48% per ride and one seat
        # drifted 3.29 -> 3.50 with no contest. New shortlists carry an
        # `anchor` flag; older ones are covered by the sibling key.json,
        # where an anchor row is any entry holding an `anchor` value.
        anchor_names: set[str] = set()
        key_path = path.parent / "key.json"
        if key_path.exists():
            anchor_names = {
                r["name"] for r in json.loads(key_path.read_text(encoding="utf-8"))
                if r.get("anchor") is not None
            }
        for row in json.loads(path.read_text(encoding="utf-8")):
            if active and not compatible(row, active.get(track)):
                continue
            name = row["name"]
            if row.get("anchor") or name in anchor_names:
                continue
            score = float(row.get("corrected") or row.get("score") or 0.0)
            passed = bool(row.get("pass")) if "pass" in row else score >= KOREA_FINAL_PASS
            ledger[(track, name)] = {
                "track": track, "name": name, "score": round(score, 2),
                "pass": passed, "round": rel.split("/")[1],
                "scored_row": deepcopy(row),
                **{key: row[key] for key in ("rubric_id", "jury_provenance") if key in row},
                # The picture this score was given to; an anchor ride checks it.
                **({"shape_id": row["shape_id"]} if row.get("shape_id") else {}),
                **({"certificate_id": row["certificate_id"]} if row.get("certificate_id") else {}),
            }
    passers = [item for item in ledger.values() if item["pass"]]
    # Keep compatible historical scores in the audit ledger, but do not
    # rebuild or seat deferred massv2 alternatives in a BOOK-only cycle.
    if book_only:
        passers = [item for item in passers if str(item["name"]).startswith("book:")]
    book_passers = [item for item in passers if str(item["name"]).startswith("book:")]
    if book_passers:
        print(f"BOOK masses seated alongside the authored ones: {len(book_passers)} "
              f"(best {max(i['score'] for i in book_passers):.2f})")
    # Ledger ghosts: seats the last bake could not rebuild (board_render
    # writes the list). They were judged on an engine that no longer makes
    # that variant; they do not get a seat until they rebuild again.
    ghosts_path = ROOT / "runs" / "board" / "unbakeable.json"
    ghosts = set()
    if ghosts_path.exists():
        ghosts = set(json.loads(ghosts_path.read_text(encoding="utf-8")))
        if ghosts:
            print(f"unbakeable on the last bake, left out: {sorted(ghosts)}")
            passers = [item for item in passers if item["name"] not in ghosts]
    if not passers:
        # Nothing reached the cut: the round does not end empty (the person's rule, 2026-11-03 "멈추면 안되지"; 684-1
        # judged 2.25 and 2.05). The best judged forms are seated as below-cut alternatives, the score and the cut
        # travel with them as notes, and the person picks; the jury's verdict is not changed.
        eligible = [item for item in ledger.values()
                    if (not book_only or str(item["name"]).startswith("book:"))
                    and item["name"] not in ghosts and (item.get("score") or 0) > 0]
        passers = [{**item, "below_cut": True, "cut": KOREA_FINAL_PASS}
                   for item in sorted(eligible, key=lambda i: i["score"], reverse=True)[:3]]
        if passers:
            print(f"no form reached the cut {KOREA_FINAL_PASS}; seating the best {len(passers)} as below-cut alternatives")

    def key_of(item):
        family = item["name"].split("~")[0].split("^")[0]
        scheme = book.get(family)
        # The canon layer competes only with itself: family_key cannot tell a
        # canonical cylinder from an experimental one, and without the layer
        # in the key one_per_family evicted the repertoire §11 promises is
        # always present. The layer's owner is the scheme record.
        layer = (scheme or {}).get("layer") or "experimental"
        if layer == "book":
            return (item["track"], layer, family)
        return (item["track"], layer) + (family_key(scheme) if scheme else (family,))

    # What each passer composed, read off the run that judged it. The runner
    # writes the part-to-whole position as the second half of the grid cell.
    def position_of(item) -> str:
        # `round` is the JUDGING directory (vlm-agent07); the run that staged
        # it is the same name without that prefix. Read against the judging
        # directory this resolved nothing at all, on every entry, and the
        # `except` below made the failure invisible.
        round_name = str(item.get("round") or "")
        if round_name.startswith("vlm-"):
            round_name = round_name[len("vlm-"):]
        summary = ROOT / "runs" / round_name / "massv2-summary.json"
        if not summary.exists():
            return "unknown"
        try:
            records = json.loads(summary.read_text(encoding="utf-8"))["records"]
        except Exception:  # noqa: BLE001 - a half-written summary is not fatal here
            return "unknown"
        for record in records:
            if record.get("name") == item["name"]:
                return str(record.get("cell") or "").split("|")[-1] or "unknown"
        return "unknown"

    curated = one_per_family(passers, key_of=key_of,
                             score_of=lambda item: item["score"])
    # One seat reserved for the best passer of each part-to-whole position,
    # before the rest fill in by score. Without it the board came back as ten
    # single bodies and one pilotis while the pool held all six positions.
    seated = {item["name"] for item in curated}
    best_of_position: dict[tuple, dict] = {}
    for item in passers:
        position = position_of(item)
        if position == "unknown":
            continue
        key = (item["track"], position)
        if key not in best_of_position or item["score"] > best_of_position[key]["score"]:
            best_of_position[key] = item
    # Guarded by FAMILY, not by name: part-to-whole is orthogonal to the
    # family key, so the best `stacked_tiers` passer is often a second member
    # of a family a higher scorer already seated, and appending it would void
    # the board's one stated invariant.
    seated_families = {key_of(item) for item in curated}
    reserved = [item for key, item in sorted(best_of_position.items())
                if item["name"] not in seated and key_of(item) not in seated_families]
    if reserved:
        print("reserved a seat for a part-to-whole position the board lacked: "
              + ", ".join(f"{item['name'][:28]} ({item['score']:.2f})"
                          for item in reserved))
        curated = curated + reserved
    # The family key is a partition of the LANGUAGE - opener, dominant verb,
    # stature - and two sentences built from different words can still be one
    # drawing: three court rings held three seats through three different
    # openers. The eye pass records who reads as whom (a blind judge, tiles
    # only, written to visual-groups.json as sentence names), and within a
    # visual group only the best score keeps its seat. The doctrine is old:
    # the cell final is judged by eyes.
    visual = ROOT / "runs" / "board" / "visual-groups.json"
    if visual.exists():
        groups = json.loads(visual.read_text(encoding="utf-8"))["groups"]
        # Entries are TRACK:sentence editions - a verdict is about the tile
        # the judge saw, and the K edition of a sentence is a different tile
        # from its O edition. Keying by bare sentence chained one edition's
        # verdict onto the other's partners and over-merged whole rows.
        def edition(name: str) -> str:
            if ":" in name:
                return name
            return "O:" + name.split("~")[0].split("^")[0]

        # Each recorded group is a CLIQUE the judge actually saw together.
        # Union-find chained overlapping groups transitively - a flat plate,
        # a rising wedge and stepped terraces shared one seat though
        # wedge-terraces was never judged as a pair - so groups no longer
        # merge with each other: an edition loses its seat only to a member
        # of a group it was directly judged in.
        cliques: list[tuple[list[str], str | None]] = []
        for group in groups:
            names = group["members"] if isinstance(group, dict) else group
            keep = group.get("keep") if isinstance(group, dict) else None
            cliques.append(([edition(n) for n in names],
                            edition(keep) if keep else None))
        member_of: dict[str, list[int]] = {}
        for index, (members, _keep) in enumerate(cliques):
            for name in members:
                member_of.setdefault(name, []).append(index)
        by_edition: dict[str, dict] = {}
        for item in curated:
            name = item["track"] + ":" +                 item["name"].split("~")[0].split("^")[0]
            held = by_edition.get(name)
            if held is None or item["score"] > held["score"]:
                by_edition[name] = item
        dropped_ids: set[int] = set()
        for members, keep in cliques:
            present = [by_edition[m] for m in members if m in by_edition]
            comparison = present + ([by_edition[keep]] if keep in by_edition else [])
            if len({row.get('rubric_id') for row in comparison}) > 1:
                continue
            if len(present) < 2 and keep is None:
                continue
            if keep is not None and keep in by_edition:
                winner = by_edition[keep]
            elif present:
                winner = max(present, key=lambda it: it["score"])
            else:
                continue
            for item in present:
                if id(item) != id(winner):
                    dropped_ids.add(id(item))
        dropped = [item for item in curated if id(item) in dropped_ids]
        for item in dropped:
            print(f"  eye-merged out: {item['name'][:48]} ({item['score']:.2f})")
        curated = [item for item in curated if id(item) not in dropped_ids]

    # One sentence, one seat per rubric: a sentence that passed both
    # juries held K6 and O2 at once, and to the client that is the same
    # building printed twice whatever the tracks' briefs did to its size.
    # Runs AFTER the eye pass: an edition the eye already merged away must not first evict its twin from the other track and then die itself, orphaning the sentence. No judge needed for this tier - same name is same drawing by
    # construction; the higher-scored compatible edition represents it.
    def comparison_key(item):
        return (item.get('rubric_id'), item['name'].split('~')[0].split('^')[0])

    best_by_sentence: dict[tuple, dict] = {}
    for item in curated:
        sentence = comparison_key(item)
        held = best_by_sentence.get(sentence)
        if held is None or item["score"] > held["score"]:
            best_by_sentence[sentence] = item
    for item in curated:
        sentence = comparison_key(item)
        if id(item) != id(best_by_sentence[sentence]):
            print(f"  cross-track duplicate out: {item['track']} "
                  f"{item['name'][:44]} ({item['score']:.2f})")
    curated = [item for item in curated
               if id(item) == id(best_by_sentence[
                   comparison_key(item)])]

    # Presentation only: the complete scored ledger remains below unchanged.
    curated = exact_presentation_aliases(curated)
    from backend.app.modules.massing.workspace_tools.presentation_aliases import current_source_loader, group_presentations
    loader = current_source_loader()
    grouped, audits = [], []
    presentation_ledger = [item for item in ledger.values()
                           if not book_only or str(item['name']).startswith('book:')]
    for identity in dict.fromkeys(item.get('rubric_id') for item in presentation_ledger):
        selected, audit = group_presentations(
            [item for item in curated if item.get('rubric_id') == identity],
            sorted((item for item in presentation_ledger if item.get('rubric_id') == identity),
                   key=lambda row: (-row['score'], row['name'])), loader)
        # Group IDs are local to each independent rubric comparison.
        if identity is not None:
            for item in selected:
                item['presentation_group'] = f"{identity}:{item['presentation_group']}"
            for entry in audit['entries']:
                entry['group_id'] = f"{identity}:{entry['group_id']}"
        grouped.extend(selected)
        audits.extend(audit['entries'])
    curated = grouped
    presentation_audit = dict(schema='mass.solid_presentation_groups.v1',
        policy='one image per verified occupied form within each rubric; original scores retained',
        entries=audits)
    board = []
    counters = {"K": 0, "O": 0}
    for track in ("K", "O"):
        for item in curated:
            if item["track"] != track:
                continue
            counters[track] += 1
            board.append({"label": f"{track}{counters[track]}",
                          "name": item["name"], "score": item["score"],
                          "round": item["round"],
                          **{key: item[key] for key in ("rubric_id", "jury_provenance") if key in item},
                          **({"shape_id": item["shape_id"]} if item.get("shape_id") else {}),
                          **({"certificate_id": item["certificate_id"]} if item.get("certificate_id") else {}),
                          **({"exact_geometry_aliases": item["exact_geometry_aliases"]}
                             if item.get("exact_geometry_aliases") else {}),
                          **{key: item[key] for key in ('presentation_group', 'presentation_comparison',
                                                       'solid_form_aliases') if key in item},
                          # A below-cut seat says so on the board (the person picks knowing the jury's verdict).
                          **({'below_cut': True, 'cut': item['cut']} if item.get('below_cut') else {})})
    # The canon is not a contestant. Section 11 promises the standard
    # repertoire is ALWAYS present, and for a season it wasn't: the canon
    # round was authored, closed-looped and never juried, so the wide slab,
    # the pilotis slab and the cylinder simply never appeared before the
    # client. Canon seats by right - base sentence, file order, jury score
    # shown when one exists but never required.
    # The representative is the canon run's own chosen VARIANT, not the bare
    # sentence: rebuilding a base name fits the unspread form to the full
    # footprint and the cylinder bakes as a squat drum. The latest canon run
    # is the owner of which variant shows each type.
    CANON_RUN = "ovs13-v4"
    canon_pick: dict[str, str] = {}
    canon_summary = ROOT / "runs" / CANON_RUN / "massv2-summary.json"
    if canon_summary.exists():
        # Fallback only - the real representative is the eye's pick below.
        # (The v3 detour proved the band IS the type's proportion: exempting
        # the canon from coverage bands locked every exemplar to its plan-wide
        # seed and the ridge flattened. Bands are back; the eye chooses which
        # band reads as the type, stature-honest.)
        for row in json.loads(canon_summary.read_text(encoding="utf-8"))["records"]:
            if row.get("status") != "compiled" or                     (row.get("plausibility") or {}).get("reasons"):
                continue
            sentence = row["name"].split("~")[0].split("^")[0]
            held = canon_pick.get(sentence)
            if held is None or (row["name"].endswith("^centred")
                                and not held.endswith("^centred")):
                canon_pick[sentence] = row["name"]
    # Eye/typology overrides: the run's cell picks optimise coverage spread,
    # but a canon tile's job is to READ as its type - the tallest honest
    # cylinder, the steepest honest ridge. Recorded per sentence, stature-
    # honest, in canon-picks.json.
    picks_path = ROOT / "runs" / "board" / "canon-picks.json"
    if picks_path.exists():
        canon_pick.update(json.loads(picks_path.read_text(encoding="utf-8")))
    canon_count = 0
    canon_paths = [] if book_only else sorted((ROOT / "inputs").glob("gen-*.json"))
    for path in canon_paths:
        for scheme in json.loads(path.read_text(encoding="utf-8"))["schemes"]:
            if scheme.get("layer") != "canon":
                continue
            canon_count += 1
            shown = canon_pick.get(scheme["name"], scheme["name"])
            judged = ledger.get(("O", shown)) or ledger.get(("O", scheme["name"]))
            board.append({"label": f"C{canon_count}",
                          "name": shown,
                          "score": judged["score"] if judged else None,
                          "round": judged["round"] if judged else "canon"})
    out = ROOT / "runs" / "board"
    out.mkdir(parents=True, exist_ok=True)
    (out / 'solid-presentation.json').write_text(
        json.dumps(presentation_audit, ensure_ascii=False, indent=2), encoding='utf-8')
    (out / "ledger.json").write_text(
        json.dumps(sorted(ledger.values(), key=lambda r: (-r["score"], r["name"])),
                   ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "board-key.json").write_text(
        json.dumps(board, ensure_ascii=False, indent=1), encoding="utf-8")
    kept = {"K": counters["K"], "O": counters["O"]}
    print(f"ledger {len(ledger)} entries, passers {len(passers)}, "
          f"board K{kept['K']} + O{kept['O']} (one per family)")
    for row in board:
        score = f"{row['score']:.2f}" if row["score"] is not None else "  - "
        print(f"  {row['label']:>4} {score} {row['name'][:52]}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
