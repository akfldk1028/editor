"""Bake the board's tiles and track sheets from board-key.json.

The board was re-baked by hand once (rule 0: after an executor change the
tiles are re-rendered before anyone looks). Republishing is a routine now,
so the baking is a tool: every overseas entry is rebuilt with the code as it
stands and drawn as a single tile plus its place in the track sheet. Korean
entries are rebuilt the same way when their brief is available; otherwise an
existing tile is kept and reported, never silently redrawn from the wrong
schedule.

    python tools/board_render.py            # rebake O tiles + both sheets
"""

from backend.app.modules.massing import paths as _mass_paths
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime


from backend.app.modules.design.generation import paths as _design_paths

import json
import shutil
import sys
from pathlib import Path

from backend.app.modules.massing.workspace_tools.band_probe import corpus  # noqa: E402
from backend.app.modules.massing.workspace_tools.book_import import entry_for_judged_row  # noqa: E402
from backend.app.modules.massing.workspace_tools.finalists import PNU, rebuild, BUILDING_TYPE  # noqa: E402
from backend.app.modules.massing.workspace_tools.vlm_shortlist import rebuild_seat, shape_id, seat_certificate

from backend.app.modules.design.generation.maas.massv2.legal import load_legal_site  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.render import render_masses  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.siting import site_open_side_direction  # noqa: E402

ROOT = _mass_paths.workspace_root()
BOARD = ROOT / "runs" / "board"
TILE = (880, 740)
SHEET_TILE = (440, 370)
SHEET_COLUMNS = 4
# The board's parcel is 효돈동 and its Korean track is sized to this brief -
# the same 과업 the Korean rubric names. Loaded from programs-korean.json,
# never typed as numbers here.
KOREA_BRIEF = "효돈동 주민센터"


def _korea_schedule():
    from backend.app.modules.design.generation.maas.massv2 import program as programme
    book = json.loads((ROOT / "inputs" / "programs-korean.json")
                      .read_text(encoding="utf-8"))
    record = next((r for r in book["schedules"]
                   if r.get("name") == KOREA_BRIEF), None)
    if record is None:
        return None
    return programme.schedule_from_record(
        record, shared_share_of_gross=book.get("shared_area_share_of_gross"))


def tile_evidence(row, source, caption, certificate=None):
    """A changed picture can be baked for review, but cannot retain its score."""
    current = shape_id(source)
    matched = bool(row.get('shape_id')) and row['shape_id'] == current
    if certificate is not None:
        matched = matched and row.get('certificate_id') == certificate['certificate_id']
    meta = dict(caption or {})
    meta['심사'] = f"{row['score']:.2f}" if matched and row.get('score') is not None else '재심사 필요'
    return meta, {'name': row['name'], 'shape_id': current,
                  'certificate_id': (certificate or {}).get('certificate_id'),
                  'scored_shape_id': row.get('shape_id'), 'requires_rejudge': not matched}


def main() -> int:
    board = json.loads((BOARD / "board-key.json").read_text(encoding="utf-8"))
    book = corpus()
    site = load_legal_site(PNU, building_type=BUILDING_TYPE)
    buildable = site.plan_at(0.0)
    axis = site_open_side_direction(site) or (1.0, 0.0)
    base = site.floor_height_m * max(
        1, int(site.far_capacity_m2 // max(1.0, site.ground_capacity_m2)))

    korea_schedule = _korea_schedule()
    per_track: dict[str, list] = {"K": [], "O": [], "C": []}
    kept, baked = 0, 0
    render_key = []
    unbakeable: list[str] = []
    # Label tiles are regenerated every bake; a leftover from the previous
    # curation carries another scheme's drawing under this label (labels are
    # reassigned each time). Clear them first so a seat that cannot be
    # rebuilt shows as missing instead of as someone else's building.
    for stale in BOARD.glob("[KOC]*.png"):
        if stale.stem[1:].isdigit():
            stale.unlink()
    for row in board:
        track = row["label"][0]
        family = row["name"].split("~")[0].split("^")[0]
        parti = book.get(family)
        source = None
        caption = None
        book_entry = entry_for_judged_row(row) if row['name'].startswith('book:') else None
        if row['name'].startswith('book:') or (parti is not None and (track in ('O', 'C') or korea_schedule is not None)):
            try:
                source, caption = rebuild_seat(row['name'], book, site, buildable, axis, base,
                                                schedule=korea_schedule if track == 'K' else None,
                                                book_entry=book_entry)
            except ValueError as fault:
                # A seat whose stored measurement no longer matches what the
                # engine builds is the ghost this loop already knows how to
                # record - it was raising instead, and one comp17 BOOK seat
                # stopped the whole bake after the executor changed.
                print(f"cannot certify: {row['label']} {fault}")
                source, caption = None, None
        # A tile that cannot be rebuilt is kept from the cache BY SCHEME NAME,
        # never by label: labels are reassigned at every curation, and keeping
        # `K8.png` from the previous bake once put another scheme's drawing
        # under ring_on_air's seat (two K seats rendered pixel-identical).
        cache = BOARD / "by-name"
        cache.mkdir(exist_ok=True)
        safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in row["name"])[:150]
        cached = cache / f"{safe}.png"
        if source is None:
            print(f"missing and unbakeable: {row['label']} {row['name']}")
            unbakeable.append(row["name"])
            continue
        baked += 1
        meta, identity = tile_evidence(row, source, caption, seat_certificate(
            row['name'], source, book, site, book_entry=book_entry))
        render_masses([(row["label"], source, meta)],
                      BOARD / f"{row['label']}.png",
                      site_ring=list(buildable.exterior.coords),
                      columns=1, tile=TILE, style="massing")
        shutil.copyfile(BOARD / f"{row['label']}.png", cached)
        import hashlib
        render_key.append({**identity, 'label': row['label'],
                           'png_sha256': hashlib.sha256((BOARD / f"{row['label']}.png").read_bytes()).hexdigest()})
        per_track[track].append((row["label"], source, None))

    # Seats the current engine cannot rebuild are ledger ghosts (judged on
    # an engine that no longer makes that variant). Recorded here; the
    # curator reads the file and leaves them out of the next board.
    # A ghost the curator left off this board was not tried this bake and
    # is not thereby certified: the list was rewritten from this board's
    # rows only, so seven comp17 BOOK ghosts vanished from it at the very
    # bake that omitted them and came back at the next curation. Names not
    # on this board carry forward; a name that baked here drops out.
    ghosts_path = BOARD / "unbakeable.json"
    if ghosts_path.exists():
        on_board = {row["name"] for row in board}
        previous = set(json.loads(ghosts_path.read_text(encoding="utf-8")))
        unbakeable = sorted(set(unbakeable) | (previous - on_board))
    ghosts_path.write_text(
        json.dumps(unbakeable, ensure_ascii=False, indent=1), encoding="utf-8")
    (BOARD / 'render-key.json').write_text(json.dumps(render_key, ensure_ascii=False, indent=2), encoding='utf-8')

    from PIL import Image
    for track in ("K", "O", "C"):
        entries = per_track[track]
        if not entries:
            continue
        columns = SHEET_COLUMNS
        rows = (len(entries) + columns - 1) // columns
        sheet = Image.new("RGB", (columns * SHEET_TILE[0],
                                  rows * SHEET_TILE[1]), "white")
        for i, (label, _source, existing) in enumerate(entries):
            tile_path = existing or (BOARD / f"{label}.png")
            tile = Image.open(tile_path).resize(SHEET_TILE)
            sheet.paste(tile, ((i % columns) * SHEET_TILE[0],
                               (i // columns) * SHEET_TILE[1]))
        sheet.save(BOARD / f"sheet_{track}.png")
    print(f"baked {baked}, kept {kept} -> {BOARD}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
