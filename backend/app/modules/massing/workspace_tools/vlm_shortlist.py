"""The VLM judging stage, wired to a run instead of run beside it.

Every part of this existed and none of it was in the delivery path. The run
selects with numeric leximin (`select.choose`), and the judges - who found the
entry masses nine of ten blind, and failed `sg_interlace` while the selector
kept picking it - only ever existed when a session spawned them by hand.

This closes that gap as a stage: it takes a finished run, renders the
selector's chosen masses as anonymous tiles under the stored rubric
(`inputs/judge-prompts.json` - fixed, never edited between rounds), and emits
the judging prompt plus a scoring template. The judges themselves are
subagents; the session runs them and writes their RANKING lines back with
`--score`, and this tool then writes `vlm-shortlist.json` naming the masses
the judges kept.

    python tools/vlm_shortlist.py <run> [count]          # stage tiles + prompt
    python tools/vlm_shortlist.py <run> --score r1.txt r2.txt [r3.txt]

The result is the sheet order for the final drawing: gates decide what may
stand, cells decide what is comparable, judges decide what is shown.
"""

from backend.app.modules.massing import paths as _mass_paths
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime


from backend.app.modules.design.generation import paths as _design_paths

import json
import re
import statistics
import sys
from pathlib import Path

from backend.app.modules.massing.workspace_tools.evaluation_contract import compatible, stage_contract, jury_provenance

ROOT = _mass_paths.workspace_root()

# The pass cut, once. It lived as `>= 3.0` here and as `3.5 - 0.5` in the
# curator's KOREA_FINAL_PASS - two literals that happened to agree.
PASS_CUT = 3.0


def rubric_for(track: str, site=None) -> str:
    """Canonical score contract plus anonymous, whitelisted site input data."""
    filename = 'judge-prompts.json' if track == 'korea' else 'judge-prompts-overseas.json'
    rubric = json.loads((ROOT / 'inputs' / filename).read_text(encoding='utf8'))['rubric']
    if site is None:
        return ('SITE INPUT DATA\nSite, legal limits, programme and budget are not supplied. '
                'Do not substitute a sample parcel or programme.\n\n' + rubric)
    evidence = site.evidence()
    unknown = 'unknown_or_not_established'
    def value(key):
        result = evidence.get(key)
        return unknown if result is None else result
    data = {
        'parcel_area_m2':value('parcel_area_m2'),
        'ground_capacity_m2':value('ground_capacity_m2'),
        'far_capacity_m2':value('far_capacity_m2'),
        'max_storeys':value('max_storeys'),
        'statutory_max_height_m':value('statutory_max_height_m'),
        'site_default_floor_height_m':value('floor_height_m'),
        'building_use_input':value('building_type'),
        'terrain_datum_measured':value('datum_measured'),
        'building_line_geometry_registered':value('building_line_geometry_registered'),
        'exact_building_line_geometry_verified':value('exact_building_line_geometry_verified'),
        'programme_schedule':'not supplied by LegalSite evidence',
        'construction_budget':'not supplied by LegalSite evidence',
    }
    return ('SITE INPUT DATA\n```json\n' + json.dumps(data, ensure_ascii=False, indent=2) +
            '\n```\nStorey count, floor height and a statutory height cap are different quantities. '
            'Unknown does not mean unrestricted or verified. Building use is supplied input, '
            'not a verified room schedule.\n\n' + rubric)


# A tile is now the mass over its own operation sequence, so the rubric has to
# say what the strip is - a juror shown an unexplained band of small drawings
# reads it as clutter and marks the scheme down for it.
BLIND_PREAMBLE = (
    "Directly view every assigned tile before scoring. Never open key.json.\n"
    "This is an architectural massing review. Assess positive volumes, sectional hierarchy, "
    "articulation, solid-void relationships and plausible architectural development. "
    "The upper image shows the delivered mass and site plan. An optional sequence strip "
    "connects base operation studies to the selected variant; only its last frame is the "
    "same final geometry as the upper mass. PLAN and SECTION panels show actual ground/upper "
    "occupancy and the located section of that same final source. "
    "Do not assume undrawn rooms, doors, stairs or supports. A missing sequence means no "
    "intermediate record was retained and is not itself a reason to deduct points.\n\n"
)


def certified_caption(source, site, thesis: str, *,
                      ground_m2: float | None = None,
                      gross_m2: float | None = None,
                      storey_m: float | None = None) -> dict:
    """The caption every jury tile carries, contest, anchor or book alike.

    Anchors once carried the thesis alone while contestants carried
    건폐율/용적률 - the ruler could be picked out of the line-up. 건폐율 is
    the building's projection as the law counts it (every volume's
    footprint united), not `source.footprint`, which keeps the largest
    grounded piece and printed 5% under a pilotis ring at full coverage.
    """

    from shapely.ops import unary_union
    from backend.app.modules.design.generation.maas.massv2.measure import gross_floor_area_m2  # noqa: E402
    # A caller with its own certificate (the book stamps 연면적 at its own
    # storey height and floor count) passes it; massv2 masses are measured
    # here at the parcel's storey, the same ruler the legal fit uses.
    ground = (float(ground_m2) if ground_m2 is not None
              else float(unary_union([v.footprint for v in source.volumes]).area))
    # At the SCHEME's own storey height, which is the height the legal gate
    # counted floors at. Measured at the parcel's default instead, a mass
    # built on 3.4 m storeys was counted in 3.0 m floors and gained 13% of
    # floor area: `cascade_ramp_tower` passed the gate at 97% of the 용적률
    # capacity and was captioned 265% on a 250% parcel - a sheet that claims
    # legality while printing a number over the cap.
    gross = (float(gross_m2) if gross_m2 is not None
             else gross_floor_area_m2(
                 source,
                 floor_height_m=float(source.metadata.get('authored_floor_height_m') or storey_m or site.floor_height_m)))
    parcel = float(site.parcel_area_m2)
    caption = {"thesis": str(thesis or "")[:180],
            "건폐율": f"{ground / parcel * 100:.0f}%",
            "용적률": f"{gross / parcel * 100:.0f}%"}
    if getattr(site, 'max_storeys', None) is not None:
        from backend.app.modules.design.generation.maas.massv2.parcel_policy import storey_limit_evidence
        is_book = 'book_height_certificate' in source.metadata
        count = storey_limit_evidence(source, site,
                storey_m=source.metadata.get('book_storey_height_m') if is_book else storey_m,
                book_floor_count=source.metadata.get('book_floor_count'), source_kind='book' if is_book else 'authored')
        caption['층수 proxy'] = f"{count['conceptual_storey_proxy']} / 한도 {count['max_storeys']}"
    return caption


def jury_caption(source, site, *, gross_m2=None, storey_m=None):
    """The anonymous numeric caption; no author's argument enters a jury image."""
    return certified_caption(source, site, '', gross_m2=gross_m2, storey_m=storey_m)


def certificate_digest(cert):
    """The existing name-bound certificate digest, before adding its own ID."""
    import hashlib
    payload = {key: value for key, value in cert.items() if key != 'certificate_id'}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:20]


def seat_certificate(name, source, book, site, *, book_entry=None):
    """Numeric evidence and exact source identity, shared by all delivery views.

    BOOK retains its imported floor-area certificate (not a new count at the
    parcel's default storey). Projection is always measured on delivered solids.
    """
    from shapely.ops import unary_union
    from backend.app.modules.design.generation.maas.massv2.measure import gross_floor_area_m2
    ground = float(unary_union([v.footprint for v in source.volumes]).area)
    storey = None
    floor_count = None
    if name.startswith('book:'):
        from backend.app.modules.massing.workspace_tools.book_import import registry
        entry = book_entry if book_entry is not None else (registry().get(name) or {})
        gross = float(entry.get('floor_area_m2') or 0)
        if gross <= 0:
            raise ValueError(f'{name}: missing BOOK floor-area certificate')
        from backend.app.modules.massing.workspace_tools.book_import import delivered_floor_evidence
        retained = entry.get('delivered_floor_evidence')
        if not retained:
            raise ValueError(f'{name}: missing BOOK floor-area measurement evidence')
        fresh = delivered_floor_evidence(source, source.metadata.get('book_original_storey_evidence') or {},
                    floor_count=entry.get('book_floor_count'),
                    storey_m=entry.get('original_book_storey_height_m'))
        if (retained != fresh or not fresh['measurement_consistent']
                or gross != fresh['actual_gfa_m2']
                or source.metadata.get('book_delivered_floor_evidence') != fresh):
            raise ValueError(f'{name}: BOOK floor-area measurement evidence does not match delivered geometry')
        storey = entry.get('book_storey_height_m') or source.metadata.get('book_storey_height_m')
        floor_count = entry.get('book_floor_count') or source.metadata.get('book_floor_count')
        basis = fresh['basis']
    else:
        record = book.get(name.split('~')[0].split('^')[0]) or {}
        storey = float(source.metadata.get('authored_floor_height_m') or record.get('floor_height_m') or site.floor_height_m)
        gross = gross_floor_area_m2(source, floor_height_m=storey)
        basis = 'delivered geometry at authored storey height'
    parcel = float(site.parcel_area_m2)
    from backend.app.modules.design.generation.maas.massv2.parcel_policy import storey_limit_evidence
    storey_gate = storey_limit_evidence(source, site, storey_m=storey,
                    book_floor_count=floor_count, source_kind='book' if name.startswith('book:') else 'authored')
    if not storey_gate['satisfied']:
        raise ValueError(f"{name}: parcel storey gate: {', '.join(storey_gate['reasons'])}")
    from backend.app.modules.design.generation.maas.massv2.parcel_policy import area_limit_evidence
    area_gate = area_limit_evidence(source, site, gross)
    if not area_gate['satisfied']:
        raise ValueError(f"{name}: parcel area gate: {', '.join(area_gate['reasons'])}")
    ground = area_gate['ground_m2']
    cert = {'name': name, 'shape_id': shape_id(source), 'site_pnu': getattr(site, 'pnu', None), 'ground_m2': ground,
            'gross_m2': gross, 'storey_m': storey, 'floor_area_basis': basis,
            'coverage_pct': ground / parcel * 100, 'far_pct': gross / parcel * 100,
            'height_m': float(source.metadata.get('authored_height_m') or 0),
            'storey_limit': storey_gate, 'area_limits': area_gate}
    if name.startswith('book:'):
        cert['delivered_floor_evidence'] = fresh
    from backend.app.modules.design.generation.maas.massv2.structure import assess_standing
    from backend.app.modules.design.generation.maas.massv2.render_mesh import is_mesh_authoritative
    standing = assess_standing(source, height_m=cert['height_m'])
    if is_mesh_authoritative(source) and not standing.stands:
        raise ValueError(f"{name}: mesh gravity screen: {', '.join(standing.reasons)}")
    cert['structure'] = standing.evidence()
    cert['certificate_id'] = certificate_digest(cert)
    return cert


def rebuild_seat(name: str, book: dict, site, buildable, axis, base, *, schedule=None, book_entry=None,
                 row: dict | None = None):
    """A board seat's delivered geometry and its caption, whatever its stack.

    massv2 names rebuild through finalists.rebuild at the declaration's own
    budget; `book:` names rebuild through book_import at the book's own
    size and height, captioned from the book's certificate. One owner for
    every tool that re-stages seats (anchor rides, full-ledger rejudges) -
    a book seat picked as an anchor was silently skipped and the ruler
    shrank to two anchors with no warning. Returns (source, caption) or
    (None, None).
    """

    if name.startswith("book:"):
        from backend.app.modules.massing.workspace_tools.book_import import book_rebuild, resolve_entry  # noqa: E402
        # A name that recurs across stages is resolved by the row it was
        # judged in; by name alone only when every stage agrees.
        if book_entry is not None:
            entry = book_entry
        else:
            try:
                entry = resolve_entry(name, row=row)
            except KeyError:
                return None, None
        if not entry:
            return None, None
        source = book_rebuild(name, site, buildable, book_entry=entry)
        if source is None:
            return None, None
        cert = seat_certificate(name, source, book, site, book_entry=entry)
        return source, certified_caption(source, site, entry.get("thesis", ""),
                                        ground_m2=cert['ground_m2'], gross_m2=cert['gross_m2'])
    from backend.app.modules.massing.workspace_tools.finalists import rebuild as _rebuild  # noqa: E402
    family = name.split("~")[0].split("^")[0]
    parti = book.get(family)
    if parti is None:
        return None, None
    # finalists.rebuild alone adds the declaration at the scheme's own storey.
    # Pre-inflating it with the site ruler cannot be undone by its max().
    source = _rebuild(name, book, site, buildable, axis, base, schedule=schedule)
    if source is None:
        return None, None
    cert = seat_certificate(name, source, book, site)
    return source, certified_caption(source, site, parti.get("formal_principle") or "",
                                     ground_m2=cert['ground_m2'], gross_m2=cert['gross_m2'])


def shape_id(source) -> str:
    """The identity of what the renderer draws, as a short hash.

    A score belongs to a picture. When the engine changes, a seat's picture
    can change while its name and its ledger score do not, and an anchor
    whose picture changed is not an anchor: three anchors carried deltas
    spread 1.32 apart because the top seat had been redrawn under a
    regulating snap, the ruler refused to move, and a whole round was
    recorded raw - unchanged pictures fell 0.4 to 1.0 with no contest.

    Geometry, not pixels: the tile label and caption are outside it, and so
    is the renderer's own code. Every field the renderer reads is inside.
    """

    import hashlib
    from dataclasses import fields, is_dataclass

    def canonical(value):
        if hasattr(value, 'geom_type'):
            # Includes interior rings; coordinate order is normalised, not rounded.
            return value.normalize().wkb_hex
        if is_dataclass(value):
            return {'type': f'{type(value).__module__}.{type(value).__qualname__}',
                    'fields': {f.name: canonical(getattr(value, f.name)) for f in fields(value)}}
        if hasattr(value, 'signature'):
            return canonical(value.signature())
        if isinstance(value, dict):
            return {str(k): canonical(v) for k, v in sorted(value.items())}
        if isinstance(value, (list, tuple)):
            return [canonical(v) for v in value]
        return value

    meta = source.metadata or {}
    payload = {'schema': 2, 'volumes': canonical(source.volumes),
               'surfaces': canonical(getattr(source, 'surfaces', ())),
               'metadata': {k: canonical(meta.get(k)) for k in
                            ('authored_height_m', 'datum_m', 'structural_bands')}}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:20]


def seat_context(site=None):
    """Everything a seat needs to be rebuilt: (book, site, buildable, axis, base)."""

    import sys as _sys

    from backend.app.modules.massing.workspace_tools.band_probe import corpus as _corpus  # noqa: E402
    from backend.app.modules.massing.workspace_tools.finalists import PNU as _PNU, BUILDING_TYPE  # noqa: E402
    from backend.app.modules.design.generation.maas.massv2.legal import load_legal_site  # noqa: E402
    from backend.app.modules.design.generation.maas.massv2.siting import site_open_side_direction  # noqa: E402
    book = _corpus()
    if site is None:
        site = load_legal_site(_PNU, building_type=BUILDING_TYPE)
    buildable = site.plan_at(0.0)
    axis = site_open_side_direction(site) or (1.0, 0.0)
    base = site.floor_height_m * max(
        1, int(site.far_capacity_m2 // max(1.0, site.ground_capacity_m2)))
    return book, site, buildable, axis, base


def ride_anchors(out: Path, key_rows: list, *, site=None) -> int:
    """Seat up to three current board entries among the tiles, anonymously.

    Absolute scores drift by judge session (measured -0.9 to -0.007 across
    rounds with an unchanged rubric), so a raw 3.0 cut is a function of the
    session's mood; the anchors' known ledger scores let --score convert
    every raw mean back onto the board's own scale. One owner for every
    stage that rides anchors (massv2 rounds, book imports): same picks,
    same rebuild, same caption. Appends to `key_rows`; returns how many.
    """

    contract = stage_contract(out, freeze=True)
    active = contract["rubric_id"] if contract else None
    board_path = ROOT / "runs" / "board" / "board-key.json"
    if not board_path.exists():
        return 0
    seats = [row for row in json.loads(board_path.read_text(encoding="utf-8"))
             if row["label"].startswith("O") and compatible(row, active)]
    if not seats:
        return 0
    import sys as _sys

    from backend.app.modules.massing.workspace_tools.band_probe import corpus as _corpus  # noqa: E402
    from backend.app.modules.massing.workspace_tools.finalists import PNU as _PNU, BUILDING_TYPE  # noqa: E402
    from backend.app.modules.design.generation.maas.massv2.legal import load_legal_site  # noqa: E402
    from backend.app.modules.design.generation.maas.massv2.render import render_masses  # noqa: E402
    from backend.app.modules.design.generation.maas.massv2.siting import site_open_side_direction  # noqa: E402
    # Top, middle and bottom of the board first, so the anchors span the
    # scale; then the rest, for when one of those cannot serve. Three
    # anchors is the ride; fewer is a weaker ruler, and it says so.
    order = []
    if seats:
        first = list(dict.fromkeys([0, len(seats) // 2, len(seats) - 1]))
        order = [seats[i] for i in first]
        order += [row for i, row in enumerate(seats) if i not in first]
    book, site, buildable, axis, base = seat_context(site)
    index = len(key_rows)
    added = 0
    # A contestant cannot be its own ruler: the round's own seats are not
    # anchors for that round (the vault arcade rode as tile t12 and stood
    # as contest tile t01 in one stage), and neither is any seat whose
    # score came from the round being re-judged.
    contestants = {str(r.get("name")) for r in key_rows}
    for row in order:
        if added >= 3:
            break
        if row["name"] in contestants or str(row.get("round") or "") == out.name:
            continue
        try:
            source, caption = rebuild_seat(row["name"], book, site, buildable, axis, base,
                                           row=row if row.get("certificate_id") else None)
        except ValueError as exc:
            print(f"   anchor {row['name'][:48]}: {exc} - not riding it")
            continue
        if source is None:
            print(f"   WARNING: anchor {row['name']} could not be rebuilt - riding without it")
            continue
        # A score belongs to a picture. A seat whose current drawing is not
        # the one its score was given to cannot calibrate anything.
        known = row.get("shape_id")
        current = shape_id(source)
        if not known:
            print(f"   anchor {row['name'][:48]}: no recorded picture identity - not riding it")
            continue
        if known != current:
            print(f"   anchor {row['name'][:48]}: picture changed since it was scored - not riding it")
            continue
        # The same entry the rebuild used: a name that recurs across stages
        # resolves by its judged row, and resolving it by name here handed
        # the certificate another stage's entry, which raised past the
        # ride's own "not riding it" and stopped the develop pairs.
        try:
            from backend.app.modules.massing.workspace_tools.book_import import entry_for_judged_row  # noqa: E402
            certificate = seat_certificate(
                row['name'], source, book, site,
                book_entry=entry_for_judged_row(row) if row.get('certificate_id') and row['name'].startswith('book:') else None)
        except ValueError as exc:
            print(f"   anchor {row['name'][:48]}: {exc} - not riding it")
            continue
        if row.get('certificate_id') != certificate['certificate_id']:
            print(f"   anchor {row['name'][:48]}: numeric certificate changed - not riding it")
            continue
        index += 1
        tile = f"t{index:02d}"
        render_masses(
            [(tile, source, {**caption, 'thesis': ''})],
            out / f"{tile}.png", site_ring=list(buildable.exterior.coords),
            columns=1, tile=(900, 820), style="massing")
        from backend.app.modules.massing.workspace_tools.presentation import append_jury_drawings
        drawings = append_jury_drawings(out / f'{tile}.png',
            [(row['name'], source, certificate['storey_m'])], buildable)
        import hashlib
        key_rows.append({"tile": tile, "name": row["name"], "anchor": row["score"],
                         "rubric_id": active,
                         "shape_id": current, 'certificate': certificate, 'jury_drawings': drawings,
                         'certificate_id': certificate['certificate_id'],
                         'png_sha256': hashlib.sha256((out / f'{tile}.png').read_bytes()).hexdigest()})
        added += 1
    if added < 3:
        print(f"   WARNING: only {added} anchor(s) rode - the session ruler is weaker")
    return added


def _with_sequence(tile_png: Path, run: str, name: str, expected_shape: str | None = None) -> None:
    """Paste the scheme's operation sequence under its axonometric, in place.

    The sequence sheet is wide and short; the tile is tall. Scaled to the
    tile's width and joined below it, the juror reads the moves that made the
    mass in the same glance as the mass - which is the pairing every massing
    convention in the literature publishes and the one this pipeline drew and
    then threw away.
    """

    from PIL import Image  # noqa: E402  (Pillow is already a render dependency)

    from backend.app.modules.massing.workspace_tools.presentation import bound_sequence
    strip_path = bound_sequence(ROOT / 'runs' / run, name, expected_shape)
    if strip_path is None or not tile_png.exists():
        return
    tile = Image.open(tile_png).convert("RGB")
    strip = Image.open(strip_path).convert("RGB")
    width = tile.width
    height = max(1, round(strip.height * width / strip.width))
    # A strip taller than the mass would make the tile a sequence sheet with a
    # picture on top; half the tile is the most the argument may take.
    if height > tile.height // 2:
        scale = (tile.height // 2) / height
        height = max(1, int(height * scale))
    strip = strip.resize((width, height), Image.LANCZOS)
    joined = Image.new("RGB", (width, tile.height + height), (255, 255, 255))
    joined.paste(tile, (0, 0))
    joined.paste(strip, (0, tile.height))
    joined.save(tile_png)


def stage(run: str, count: int) -> int:
    from backend.app.modules.massing.workspace_tools.judge_tiles import main as make_tiles  # noqa: E402  (django inside)

    out_name = f"vlm-{run}"
    make_tiles(run, str(count), out_name)
    out = ROOT / "runs" / out_name
    # The rubric matches the track: overseas rounds were being judged against
    # the Korean 과업 and every verdict said 규모 과대 about a track that has
    # no brief. Korea keeps "rubric"; overseas rounds use "rubric_overseas".
    track = (json.loads((ROOT / "runs" / run / "massv2-summary.json")
                        .read_text(encoding="utf-8"))
             .get("provenance") or {}).get("track")
    # Anchors: two or three seated board entries ride along as ordinary
    # anonymous tiles. Absolute scores drift by judge session (measured
    # -0.9 to -0.007 across rounds with an unchanged rubric), so a raw 3.0
    # cut is a function of the session's mood; the anchors' known ledger
    # scores let --score convert every raw mean back onto the board's own
    # scale. v2 had this discipline and v3 had silently dropped it.
    key_rows = json.loads((out / "key.json").read_text(encoding="utf-8"))
    # Every contest tile records the identity of the picture it was judged
    # as, so it can serve as an anchor later only while that picture holds.
    book, site, buildable, axis, base = seat_context()
    (out / "PROMPT.txt").write_text(BLIND_PREAMBLE + rubric_for(track or "overseas", site=site),
                                    encoding="utf-8")
    stage_contract(out, freeze=True)
    from backend.app.modules.massing.workspace_tools.band_probe import schedule_of
    from backend.app.modules.design.generation.maas.massv2.render import render_masses
    from backend.app.modules.massing.workspace_tools.presentation import write_sequence
    schedule = schedule_of(run) if track == 'korea' else None
    for row in key_rows:
        if row.get("anchor") is not None:
            continue
        source, caption = rebuild_seat(row["name"], book, site, buildable, axis, base, schedule=schedule)
        if source is None:
            raise ValueError(f"cannot bind staged tile to source: {row['name']}")
        # Render and stamp the same object. Rebuilding only for the hash would
        # silently certify a different picture produced by judge_tiles.
        render_masses([(row['tile'], source, {**caption, 'thesis': ''})],
                      out / f"{row['tile']}.png", site_ring=list(buildable.exterior.coords),
                      columns=1, tile=(900, 820), style='massing')
        row['shape_id'] = shape_id(source)
        row['certificate'] = seat_certificate(row['name'], source, book, site)
        row['certificate_id'] = row['certificate']['certificate_id']
        from backend.app.modules.massing.workspace_tools.presentation import append_jury_drawings
        row['jury_drawings'] = append_jury_drawings(out / f"{row['tile']}.png",
            [(row['name'], source, row['certificate']['storey_m'])], buildable)
        write_sequence(row['name'], source, book=book, site=site,
                       buildable=buildable, axis=axis, out_dir=ROOT / 'runs' / run,
                       certificate=row['certificate'], anonymous=True)
    if track != "korea":
        ride_anchors(out, key_rows, site=site)
    (out / "key.json").write_text(
        json.dumps(key_rows, ensure_ascii=False, indent=1), encoding="utf-8")
    # The argument under the outcome, for every contest tile that has one.
    for row in json.loads((out / "key.json").read_text(encoding="utf-8")):
        if row.get("anchor") is not None:
            continue
        _with_sequence(out / f"{row['tile']}.png", run, row['name'], row.get('shape_id'))
    import hashlib
    for row in key_rows:
        row['png_sha256'] = hashlib.sha256((out / f"{row['tile']}.png").read_bytes()).hexdigest()
    (out / 'key.json').write_text(json.dumps(key_rows, ensure_ascii=False, indent=1), encoding='utf-8')
    tiles = sorted(p.name for p in out.glob("t*.png"))
    print(f"{len(tiles)} tiles staged -> {out}")
    print(f"judges read: {out / 'PROMPT.txt'} + the tiles; "
          f"then rerun with --score <their outputs>")
    return 0


# A tile block opens on its own line - every juror file ever written puts
# TILE at the start of a line, with or without the `t` and with or without
# the leading zero ("TILE 7" and "TILE t07" both appear in the ledger).
_TILE_OPENS = re.compile(r"^\s*TILE\s+t?0*(\d+)\b")
_WEIGHTED = re.compile(r"WEIGHTED\s+(\S+)")
_RUBRIC_WEIGHT = re.compile(r"\*\*([A-Z]+)\s*\(weight\s+([0-9.]+)\)\*\*")
# A juror's WEIGHTED is its own arithmetic over the four counts it scored.
# Rounded to two decimals by the juror, so a difference up to this is not an
# error; past it the stated number is not the weighted mean of the stated
# counts, and the counts - the judgments - are what the round keeps.
_WEIGHTED_TOLERANCE = 0.011


def rubric_weights(prompt_text: str) -> dict[str, float]:
    """{COUNT: weight} as the staged PROMPT states them, e.g. FEASIBILITY 0.35."""
    return {name: float(w) for name, w in _RUBRIC_WEIGHT.findall(prompt_text)}


class VerdictError(ValueError):
    """A juror's file cannot be read tile by tile, so the round does not score.

    Numbers that are not bound to the tile the juror was looking at are
    worse than no numbers: they seat the wrong mass on the board, and
    nothing downstream - not the curator, not the ledger, not an eye check
    on the sheet - can tell a mis-bound score from an honest one.
    """


def read_verdict(path: Path, key_tiles, weights: dict[str, float] | None = None) -> dict[str, float]:
    """One juror's file as {tile: weighted score}, read block by block.

    A TILE line opens a block and the next TILE line closes it, so the
    WEIGHTED a tile gets is the one the juror wrote underneath it. The
    reading this replaces was a single non-greedy regex over the whole file
    (`TILE ... WEIGHTED`), which let a juror who wrote a TILE block and
    omitted its WEIGHTED line take the NEXT tile's number: two tiles shared
    one score, one tile's score belonged to another drawing, and the round
    published both without a word. judge.sh cannot catch it either - it
    counts `^TILE` lines, and in that failure the count is right and only
    the binding is wrong.

    So this refuses instead of skipping, on every way the binding can go
    wrong: a block with no WEIGHTED, a WEIGHTED that is not a score in
    1..5, and a tile the round's key.json does not contain. A tile stated
    twice with the same number is a juror restating its own table
    (ovs17-en r3 wrote a seven-row summary under its seven blocks) and the
    last statement stands, as it always did; a tile stated twice with two
    different numbers is a contradiction no reader can resolve, so that
    refuses too.
    """

    name = Path(path).name
    # PowerShell UTF-8 writers may prefix a BOM; it is encoding metadata,
    # not part of the first TILE identifier. Keep the ballot bytes unchanged.
    lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    opens = [i for i, line in enumerate(lines) if _TILE_OPENS.match(line)]
    seen: dict[str, float] = {}
    for n, start in enumerate(opens):
        end = opens[n + 1] if n + 1 < len(opens) else len(lines)
        tile = f"t{int(_TILE_OPENS.match(lines[start]).group(1)):02d}"
        if tile not in key_tiles:
            raise VerdictError(
                f"{name}: scores {tile}, which this round has no tile for - "
                "the juror was reading a different stage")
        found = next((m for m in (_WEIGHTED.search(line) for line in
                                  lines[start:end]) if m), None)
        if found is None:
            raise VerdictError(
                f"{name}: TILE {tile} has no WEIGHTED line in its block - "
                "refusing to score the round rather than lend it the next "
                "tile's number")
        raw = found.group(1)
        try:
            value = float(raw)
        except ValueError:
            raise VerdictError(
                f"{name}: TILE {tile} has WEIGHTED {raw!r}, which is not a "
                "number") from None
        if not 1.0 <= value <= 5.0:
            raise VerdictError(
                f"{name}: TILE {tile} has WEIGHTED {value}, outside the "
                "rubric's 1..5 - a stray number read as a score moves the "
                "session drift for every other tile")
        if weights:
            # The WEIGHTED line was taken on trust; a juror whose arithmetic
            # slipped published a number its own counts do not give. Recompute
            # it from the counts in this block when every count is there.
            counts = {}
            for line in lines[start:end]:
                m = re.match(r"^\s*([A-Z]+)\s+([0-9.]+)\s*\|", line)
                if m and m.group(1) in weights:
                    counts[m.group(1)] = float(m.group(2))
            if set(counts) == set(weights):
                if not all(1.0 <= c <= 5.0 for c in counts.values()):
                    raise VerdictError(
                        f"{name}: TILE {tile} has a count outside the rubric's 1..5")
                computed = round(sum(weights[k] * counts[k] for k in weights)
                                 / sum(weights.values()), 2)
                if abs(computed - value) > _WEIGHTED_TOLERANCE:
                    print(f"   NOTE: {name} {tile} wrote WEIGHTED {value}; its "
                          f"counts give {computed} - the counts stand")
                value = computed
        if tile in seen and seen[tile] != value:
            raise VerdictError(
                f"{name}: TILE {tile} is scored twice and the two disagree "
                f"({seen[tile]} then {value}) - no reader can say which the "
                "juror meant")
        seen[tile] = value
    return seen


def score(run: str, paths: list[str]) -> int:
    out = ROOT / "runs" / f"vlm-{run}"
    contract = stage_contract(out, freeze=True)
    active = contract["rubric_id"] if contract else None
    evaluation = {"rubric_id": active, "jury_provenance": jury_provenance(out)} if active else {}
    key = {r["tile"]: r for r in json.loads((out / "key.json").read_text(encoding="utf-8"))}
    import hashlib
    for tile, row in key.items():
        if row.get('png_sha256'):
            picture = out / f'{tile}.png'
            if not picture.exists() or hashlib.sha256(picture.read_bytes()).hexdigest() != row['png_sha256']:
                raise ValueError(f'{tile}: staged image changed; restage and rejudge')
    per_tile: dict[str, list[float]] = {t: [] for t in key}
    prompt = out / "PROMPT.txt"
    weights = rubric_weights(prompt.read_text(encoding="utf-8")) if prompt.exists() else None
    for path in paths:
        seen = read_verdict(Path(path), key, weights)
        missing = [t for t in key if t not in seen]
        if missing:
            print(f"   WARNING: {Path(path).name} scored no line for "
                  f"{', '.join(missing)}")
        for tile, value in seen.items():
            per_tile[tile].append(value)
    unscored = [t for t, v in per_tile.items() if not v]
    if unscored:
        print(f"   WARNING: no juror scored {', '.join(unscored)} - "
              "dropped from the shortlist")
    ranked = sorted(
        ((statistics.mean(v), t) for t, v in per_tile.items() if v), reverse=True)
    # Session drift, measured off the anchors: how much softer or harder this
    # jury was than the ledger's own scale. corrected = raw - drift, and the
    # curator already prefers `corrected` over `score`.
    deltas = [s - float(key[t]["anchor"])
              for s, t in ranked if key[t].get("anchor") is not None
              and (compatible(key[t], active) if active else True)]
    # Median, not mean: one wild anchor (a jury that simply dislikes one
    # seated scheme) must not drag every candidate's correction with it -
    # the mean once pushed a candidate to 5.04 on a 5-point scale.
    drift = statistics.median(deltas) if deltas else 0.0
    spread = (max(deltas) - min(deltas)) if deltas else 0.0
    # How the `corrected` column was made, on every row: a round with no
    # anchors and a round whose anchors disagreed both wrote raw scores
    # under the same key as a corrected round, and the curator read them
    # on one scale.
    correction = "median_drift" if deltas else "none_no_anchors"
    if deltas:
        print(f"   anchors {len(deltas)}, session drift {drift:+.2f} (median), "
              f"delta spread {spread:.2f}")
    if spread > 1.0 and len(deltas) >= 3:
        # One anchor the jury simply disliked is not "no constant shift
        # fits": comp18's massv2 jury sat at -1.05 on two anchors and -1.62
        # on the third (spread 1.12), the BOOK jury the same night at -1.10
        # (spread 0.27). One track was corrected +1.10 and the other not at
        # all, a raw 3.52 met a raw 3.52 on the board as 3.52 against 4.62,
        # and the sheet was BOOK three times over. Drop the one anchor
        # farthest from the median; if the rest agree, their shift stands.
        farthest = max(deltas, key=lambda d: abs(d - drift))
        kept = [d for d in deltas if d is not farthest]
        if kept and (max(kept) - min(kept)) <= 1.0:
            drift = statistics.median(kept)
            print(f"   one anchor off by {farthest - drift:+.2f} dropped; the other "
                  f"{len(kept)} agree (spread {max(kept) - min(kept):.2f}), "
                  f"session drift {drift:+.2f}")
            spread = max(kept) - min(kept)
            correction = "median_drift_one_anchor_dropped"
    if spread > 1.0:
        # No constant shift fits this jury. Applying one anyway once crowned a
        # candidate at 5.04/5 over a champion the jury simply disliked. When
        # the anchors cannot agree, do not shift: record raw (a harsh jury
        # underrates everyone equally - conservative for seating) and flag the
        # round so the curator and the next reader know the ruler slipped.
        print("   WARNING: anchors disagree beyond any constant shift "
              f"(spread {spread:.2f}) - recording RAW scores, no correction; "
              "an eye check should confirm any board-top change.")
        drift = 0.0
        correction = "none_anchor_spread"
    result = [{
        **evaluation,
        "tile": t, "score": round(s, 2),
        "corrected": round(min(5.0, max(1.0, s - drift)), 2),
        "pass": (s - drift) >= PASS_CUT,
        "correction": correction,
        **({"anchor_spread": round(spread, 2)} if spread > 1.0 else {}),
        "name": key[t]["name"], "coverage_pct": key[t].get("coverage_pct"),
        **({"shape_id": key[t]["shape_id"]} if key[t].get("shape_id") else {}),
        **({"certificate_id": key[t]["certificate_id"]} if key[t].get("certificate_id") else {}),
        # Anchors calibrate the session; they are not contestants. Without
        # this flag the curator re-recorded each anchor's ride-corrected
        # score as its current score, and the ruler measured itself: anchor
        # spread compressed 23-48% per ride and a seat gained +0.21 over two
        # rides with no contest. The flag lets the curator skip them.
        **({"anchor": True} if key[t].get("anchor") is not None else {}),
    } for s, t in ranked]
    (out / "vlm-shortlist.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    # The round's manifest: what the curator needs to seat it, written by
    # the tool that scored it. ROUNDS was a hand-edited list in
    # board_curate.py - a scored round nobody typed in was invisible to the
    # board, and "forgotten" looked exactly like "excluded".
    summary_path = ROOT / "runs" / run / "massv2-summary.json"
    track = "O"
    if summary_path.exists():
        provenance = (json.loads(summary_path.read_text(encoding="utf-8"))
                      .get("provenance") or {})
        track = "K" if provenance.get("track") == "korea" else "O"
    (out / "round.json").write_text(json.dumps({
        **evaluation,
        "track": track,
        "kind": "corrected" if run.startswith("board-rejudge") else "shortlist",
        "cut": PASS_CUT, "correction": correction,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    for row in result:
        print(f"   {row['score']:.2f}  {row['name'][:56]}")
    print(f"-> {out / 'vlm-shortlist.json'}")
    return 0


if __name__ == "__main__":
    if "--verify" in sys.argv:
        # One juror file against the round's key: the same reading --score
        # does, so a file the scorer would refuse is refused at the jury
        # step, where the juror can be run again, instead of at the end of
        # the cycle. judge.sh counted `^TILE` lines and passed files whose
        # scores were not bound to their tiles.
        i = sys.argv.index("--verify")
        out = ROOT / "runs" / f"vlm-{sys.argv[1]}"
        key_tiles = {r["tile"] for r in json.loads((out / "key.json").read_text(encoding="utf-8"))}
        try:
            prompt = out / "PROMPT.txt"
            weights = rubric_weights(prompt.read_text(encoding="utf-8")) if prompt.exists() else None
            verdict = read_verdict(Path(sys.argv[i + 1]), key_tiles, weights)
        except VerdictError as exc:
            print(f"REFUSED: {exc}")
            sys.exit(1)
        missing = sorted(key_tiles - set(verdict))
        if missing:
            print(f"REFUSED: no score for {', '.join(missing)}")
            sys.exit(1)
        print(f"ok: {len(verdict)} tiles bound to scores")
        sys.exit(0)
    if "--score" in sys.argv:
        i = sys.argv.index("--score")
        sys.exit(score(sys.argv[1], sys.argv[i + 1:]))
    sys.exit(stage(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 12))
