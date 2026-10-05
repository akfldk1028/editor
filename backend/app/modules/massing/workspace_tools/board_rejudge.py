"""Re-judge the board's overseas seats after a renderer or executor change.

Rule 0 says a changed drawing is re-baked before anyone looks; its corollary
is that a changed drawing's SCORE is stale too - the cylinder tower's 3.00
was judged in the scaffolding the smooth renderer has since removed. This
stages the current board's O entries as anonymous shuffled tiles under the
overseas rubric; three blind judges score them, and the result joins the
curator's rounds as a corrected pass (newest-last overrides).

    python tools/board_rejudge.py <round-name>       # e.g. board-rejudge-1
      -> runs/vlm-<round-name>/ : tiles + PROMPT.txt + key.json
    python tools/vlm_shortlist.py <round-name> --score r1 r2 r3
"""

from backend.app.modules.massing import paths as _mass_paths
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime


from backend.app.modules.design.generation import paths as _design_paths

import json
import random
import sys
from pathlib import Path

from backend.app.modules.massing.workspace_tools.band_probe import corpus  # noqa: E402
from backend.app.modules.massing.workspace_tools.finalists import PNU, rebuild, BUILDING_TYPE  # noqa: E402

from backend.app.modules.design.generation.maas.massv2.legal import load_legal_site  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.render import render_masses  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.siting import site_open_side_direction  # noqa: E402

ROOT = _mass_paths.workspace_root()


def main(round_name: str, scope: str = "") -> int:
    if scope == "--ledger":
        # One ruler over everything: a corrected round that covers only the
        # seated entries leaves their merged-out partners holding old-rubric
        # scores, and the next curation compares the two scales raw - the
        # re-judged seats lost to stale numbers. So the whole passing ledger
        # is judged in one round, and every overseas score is the same era.
        rows = json.loads((ROOT / "runs" / "board" / "ledger.json")
                          .read_text(encoding="utf-8"))
        names = [r["name"] for r in rows if r["track"] == "O" and r["pass"]]
    elif scope == "--ever":
        # A NEW ruler must see everything any ruler ever passed, not only
        # what the last ruler left standing: the ledger's pass flag is the
        # newest round's verdict, so a scheme the buildability ruler had
        # dropped to 2.97 (the twisting tower) would never meet the
        # international rubric at all. Union of every round's passers.
        from backend.app.modules.massing.workspace_tools.board_curate import rounds  # noqa: E402
        seen: dict[str, None] = {}
        for track, rel, _kind in rounds():
            path = ROOT / rel
            if track != "O" or not path.exists():
                continue
            key_path = path.parent / "key.json"
            anchors = set()
            if key_path.exists():
                anchors = {r["name"] for r in json.loads(key_path.read_text(encoding="utf-8"))
                           if r.get("anchor") is not None}
            for row in json.loads(path.read_text(encoding="utf-8")):
                if row.get("anchor") or row["name"] in anchors:
                    continue
                score = float(row.get("corrected") or row.get("score") or 0.0)
                passed = bool(row.get("pass")) if "pass" in row else score >= 3.0
                if passed:
                    seen.setdefault(row["name"], None)
        names = list(seen)
    else:
        board = json.loads((ROOT / "runs" / "board" / "board-key.json")
                           .read_text(encoding="utf-8"))
        names = [row["name"] for row in board if row["label"].startswith("O")]
    random.Random(20260901).shuffle(names)

    book = corpus()
    site = load_legal_site(PNU, building_type=BUILDING_TYPE)
    buildable = site.plan_at(0.0)
    axis = site_open_side_direction(site) or (1.0, 0.0)
    base = site.floor_height_m * max(
        1, int(site.far_capacity_m2 // max(1.0, site.ground_capacity_m2)))
    parcel = float(site.parcel_area_m2)

    out = ROOT / "runs" / f"vlm-{round_name}"
    out.mkdir(parents=True, exist_ok=True)
    # A stale stage lies twice, the same way it does in `stage.sh`: leftover
    # tiles inflate the round and leftover juror files let `score` bind an
    # old session's per-tile numbers to a new key's names. The shuffle is
    # seeded, so a changed ledger reshuffles the mapping and the lie is
    # silent.
    for stale in list(out.glob("t*.png")) + list(out.glob("r?.txt")):
        stale.unlink()
    key = []
    made = 0
    from backend.app.modules.massing.workspace_tools.vlm_shortlist import rebuild_seat, seat_certificate, shape_id  # noqa: E402
    for name in names:
        # One rebuild for every seat, book or massv2, with the certified
        # caption every jury tile carries (this round used to caption the
        # thesis alone, and skipped book seats as "no parti").
        source, caption = rebuild_seat(name, book, site, buildable, axis, base)
        if source is None:
            print(f"skip (rebuild failed): {name}")
            continue
        made += 1
        tile = f"t{made:02d}"
        render_masses(
            [(tile, source, {**caption, 'thesis': ''})],
            out / f"{tile}.png", site_ring=list(buildable.exterior.coords),
            columns=1, tile=(900, 820), style="massing",
        )
        import hashlib
        certificate = seat_certificate(name, source, book, site)
        key.append({"tile": tile, "name": name, 'shape_id': shape_id(source),
                    'certificate': certificate, 'certificate_id': certificate['certificate_id'],
                    'png_sha256': hashlib.sha256((out / f'{tile}.png').read_bytes()).hexdigest()})

    # The overseas ruler from its owner (vlm_shortlist.rubric_for).
    from backend.app.modules.massing.workspace_tools.vlm_shortlist import BLIND_PREAMBLE, rubric_for  # noqa: E402
    (out / "PROMPT.txt").write_text(BLIND_PREAMBLE + rubric_for("overseas", site=site), encoding="utf-8")
    (out / "key.json").write_text(
        json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{made} tiles staged -> {out}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "board-rejudge",
                  sys.argv[2] if len(sys.argv) > 2 else ""))
