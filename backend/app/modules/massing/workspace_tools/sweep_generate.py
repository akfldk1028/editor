"""Generate grammar-valid sentences at base-volume scale.

The authored corpus explores the language a few sentences at a time; the
combinatorial space of (opener x profile x modifier verbs x params) is tens
of thousands. This generator samples that space wide - seeded, reproducible -
and keeps ONLY what the living validator accepts, so correctness is owned by
the validator (which derives verbs/params from the executor), not by tables
here. The whole point is the funnel: generate wide, let the gates and cells
and juries pick the good ones.

Sweep books are written OUTSIDE inputs/ on purpose: the corpus glob
(inputs/gen-*.json) is the authored canon, and a thousand generated sentences
must not join it. Winners get promoted by hand into inputs/gen-sweep-picks
after a jury - the same door every sentence walks through.

    python tools/sweep_generate.py <count> <out.json> [seed]
"""

from backend.app.modules.massing import paths as _mass_paths
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime


from backend.app.modules.design.generation import paths as _design_paths

import json
import random
import sys
from pathlib import Path

ROOT = _mass_paths.workspace_root()

# Openers and their body parameters. Heights stay clear of the stature
# thresholds' knife edges; storeys spread across the site's plausible band.
_PROFILES = ("square", "oval", "stadium", "chamfered", "trapezoidal",
             "kite", "hexagon", "faceted", "triangular", "concave_l")
_OPENERS = (
    ("extrude", lambda r: {"profile": r.choice(_PROFILES),
                           "height": round(r.choice((0.25, 0.3, 0.5, 0.6, 0.8, 0.85)), 2),
                           "storeys": r.choice((2, 3, 4, 5, 6))}),
    ("loop", lambda r: {"profile": r.choice(_PROFILES),
                    "bar": round(r.uniform(0.2, 0.3), 2),
                        "height": round(r.choice((0.25, 0.3, 0.5)), 2),
                        "storeys": r.choice((1, 2, 3))}),
    ("aggregate", lambda r: {"profile": r.choice(_PROFILES),
                         "n": r.choice((2, 3, 4, 5, 6)),
                             "spread": round(r.uniform(1.1, 1.5), 2),
                             "height": round(r.choice((0.3, 0.5, 0.6)), 2),
                             "storeys": r.choice((2, 3)),
                             "tie": r.choice((0, 0, 0.2))}),
    ("stack", lambda r: {"profile": r.choice(_PROFILES),
                     "n": r.choice((3, 4, 5)),
                         "contrast": round(r.uniform(1.25, 2.0), 2),
                         "height": round(r.choice((0.6, 0.8, 0.9)), 2)}),
)

# Modifier verbs with safe param recipes (values inside their ranges, away
# from gate thresholds). Enum params are small hand tables - any bad combo
# is caught by the in-process validator below, which is the actual owner.
_AIM = ("open", "back", "cross")
# Every modifier the executor knows, with its REAL parameter names. The old
# table wrote twist:{turn}, carve:{depth,toward}, grade:{mode}, bend:{turn},
# shear:{run}, notch:{depth}, inscribe:{share} - none of which exist, so the
# validator refused every draw carrying one and the sweep could say only
# about half the language. Wide draws came back as the same boxes with
# sections because the other half was unsayable, not unwanted. Names come
# from validate_authored.VERBS, which derives them from the executor.
_MODS = (
    # section
    ("gable", lambda r: {"pitch": round(r.uniform(0.5, 1.15), 2), "along": "long",
                         "bays": r.choice((1, 1, 2, 3, 4))}),
    ("butterfly", lambda r: {"pitch": round(r.uniform(0.5, 0.9), 2),
                             "at": round(r.uniform(0.3, 0.6), 2)}),
    ("mansard", lambda r: {"pitch": round(r.uniform(0.6, 1.0), 2),
                           "shoulder": round(r.uniform(0.15, 0.35), 2)}),
    ("vault", lambda r: {"rise": round(r.uniform(0.5, 1.1), 2),
                         "bays": r.choice((1, 1, 2, 3))}),
    ("fold", lambda r: {"folds": r.choice((1, 2, 3)),
                        "pitch": round(r.uniform(0.35, 0.7), 2)}),
    ("crown", lambda r: {"form": r.choice(("dome", "dish", "saddle")),
                         "sag": round(r.uniform(0.2, 0.45), 2)}),
    ("roof", lambda r: {"rise": round(r.uniform(0.4, 1.3), 2),
                        "eave": round(r.uniform(0.15, 0.45), 2),
                        "corners": r.choice(("opposite", "adjacent", "one", "all")),
                        "sag": round(r.uniform(0.0, 0.5), 2),
                        "thin": round(r.uniform(0.07, 0.2), 2)}),
    ("grade", lambda r: {"smooth": True, "run": round(r.uniform(0.5, 0.85), 2),
                         "toward": "open", "walk": r.random() < 0.5}),
    ("grade", lambda r: {"steps": r.choice((2, 3, 4)),
                         "run": round(r.uniform(0.4, 0.7), 2), "toward": "open"}),
    # ground
    ("sink", lambda r: {"depth": round(r.uniform(0.15, 0.5), 2)}),
    ("inscribe", lambda r: {"size": round(r.uniform(0.2, 0.5), 2),
                            "depth": round(r.uniform(0.15, 0.45), 2)}),
    # in the air
    ("lift", lambda r: {"clearance": round(r.uniform(0.25, 0.4), 2)}),
    ("cantilever", lambda r: {"reach": round(r.uniform(0.2, 0.32), 2),
                              "levels": r.choice((2, 3)), "toward": "open"}),
    ("canopy", lambda r: {"reach": round(r.uniform(0.2, 0.4), 2),
                          "at": round(r.uniform(0.6, 1.0), 2), "toward": "open"}),
    ("lodge", lambda r: {"size": round(r.uniform(0.25, 0.5), 2),
                         "over": round(r.uniform(0.15, 0.5), 2),
                         "height": round(r.uniform(0.3, 0.8), 2)}),
    # plan
    ("split", lambda r: {"ratio": round(r.uniform(0.32, 0.55), 2),
                         "gap": r.choice((0, 0, 3, 6, 9)),
                         "along": r.choice(("long", "cross"))}),
    ("compress", lambda r: {"ratio": round(r.uniform(0.6, 0.78), 2), "toward": "cross"}),
    ("expand", lambda r: {"ratio": round(r.uniform(1.15, 1.35), 2), "toward": "open"}),
    ("taper", lambda r: {"ratio": round(r.uniform(0.5, 0.8), 2)}),
    ("pinch", lambda r: {"ratio": round(r.uniform(0.5, 0.72), 2),
                         "segments": r.choice((2, 3))}),
    ("inflate", lambda r: {"ratio": round(r.uniform(1.1, 1.3), 2)}),
    ("offset", lambda r: {"ratio": round(r.uniform(0.15, 0.35), 2),
                          "toward": r.choice(_AIM)}),
    ("shift", lambda r: {"ratio": round(r.uniform(0.15, 0.35), 2),
                         "toward": r.choice(_AIM)}),
    # turning
    ("twist", lambda r: {"degrees": r.choice((12, 18, 24, 30))}),
    ("rotate", lambda r: {"degrees": r.choice((-30, -20, 20, 30, 45))}),
    ("skew", lambda r: {"degrees": r.choice((10, 15, 20)), "toward": "open"}),
    ("bend", lambda r: {"degrees": r.choice((15, 20, 30)),
                        "segments": r.choice((2, 3))}),
    ("stagger", lambda r: {"ratio": round(r.uniform(0.15, 0.3), 2),
                         "toward": r.choice(_AIM)}),
    ("fracture", lambda r: {"n": r.choice((2, 3)), "degrees": r.choice((8, 12, 20)),
                            "slot": round(r.uniform(0.05, 0.15), 2)}),
    # cutting
    ("carve", lambda r: {"size": round(r.uniform(0.25, 0.5), 2),
                         "at": round(r.uniform(0.2, 0.8), 2),
                         "reach": round(r.uniform(0.4, 0.7), 2)}),
    ("notch", lambda r: {"size": round(r.uniform(0.2, 0.4), 2),
                         "at": round(r.uniform(0.2, 0.8), 2)}),
    ("puncture", lambda r: {"n": r.choice((1, 2, 3)),
                            "size": round(r.uniform(0.15, 0.35), 2)}),
    ("extract", lambda r: {"size": round(r.uniform(0.2, 0.4), 2),
                           "gap": r.choice((2, 4, 6)),
                           "height": round(r.uniform(0.4, 0.9), 2)}),
    # bodies against bodies
    ("nest", lambda r: {"size": round(r.uniform(0.3, 0.55), 2),
                        "proud": round(r.uniform(0.3, 0.8), 2),
                        "turn": r.choice((-40, -25, 20, 30, 45))}),
    ("overlap", lambda r: {"bite": round(r.uniform(0.2, 0.55), 2),
                           "slip": round(r.uniform(0.1, 0.45), 2),
                           "height": round(r.uniform(0.4, 0.9), 2)}),
    ("interlock", lambda r: {"bite": round(r.uniform(0.35, 0.7), 2),
                             "size": round(r.uniform(0.3, 0.5), 2),
                             "reach": round(r.uniform(0.2, 0.5), 2)}),
    ("merge", lambda r: {"height": round(r.uniform(0.4, 0.9), 2)}),
    ("branch", lambda r: {"n": r.choice((2, 3)),
                          "reach": round(r.uniform(0.25, 0.5), 2),
                          "height": round(r.uniform(0.3, 0.7), 2)}),
    ("embed", lambda r: {"size": round(r.uniform(0.25, 0.45), 2),
                         "depth": round(r.uniform(0.2, 0.5), 2),
                         "height": round(r.uniform(0.4, 0.9), 2)}),
    ("intersect", lambda r: {"size": round(r.uniform(0.25, 0.45), 2),
                             "degrees": r.choice((20, 35, 50)),
                             "climb": round(r.uniform(0.2, 0.5), 2)}),
)

# EXTREME mode: one gesture, all the way. The mid-range sweep produced
# competent middling masses by construction; the offices the board is
# measured against live at the edges - the deepest cantilever, the full
# twist, the tallest thin, the lowest wide. One dominant verb at its
# legal limit, one optional bar-maker, nothing else to muddy the move.
_EXTREME_OPENERS = (
    ("extrude", lambda r: {"profile": r.choice(_PROFILES),
                           "height": r.choice((0.2, 0.9)),
                           "storeys": r.choice((2, 8, 10))}),
    ("loop", lambda r: {"bar": r.choice((0.18, 0.32)),
                        "height": r.choice((0.2, 0.6)),
                        "storeys": r.choice((1, 4))}),
    ("aggregate", lambda r: {"n": r.choice((7, 8, 9)),
                             "spread": r.choice((1.05, 1.6)),
                             "height": 0.3, "storeys": r.choice((1, 2)), "tie": 0}),
    ("stack", lambda r: {"n": r.choice((6, 7)),
                         "contrast": r.choice((2.2, 2.5)),
                         "height": 0.95}),
)
_EXTREME_MODS = (
    ("twist", lambda r: {"degrees": r.choice((40, 50, 60))}),
    ("cantilever", lambda r: {"reach": 0.34, "levels": 3, "toward": "open"}),
    ("taper", lambda r: {"ratio": r.choice((0.4, 0.45))}),
    ("lift", lambda r: {"clearance": 0.4}),
    ("stagger", lambda r: {"ratio": 0.38, "toward": "open"}),
    ("carve", lambda r: {"size": 0.6, "at": 0.5, "reach": 0.8}),
    ("grade", lambda r: {"smooth": True, "run": 0.9, "toward": "open",
                         "walk": r.random() < 0.5}),
    ("pinch", lambda r: {"ratio": 0.45, "segments": 3}),
    ("bend", lambda r: {"degrees": 45, "segments": 3}),
    ("gable", lambda r: {"pitch": 1.2, "along": "long", "bays": r.choice((1, 5))}),
    ("nest", lambda r: {"size": 0.6, "proud": 0.95, "turn": r.choice((-45, 45))}),
    ("puncture", lambda r: {"n": 3, "size": 0.4}),
    ("roof", lambda r: {"rise": 1.5, "eave": 0.5,
                        "corners": r.choice(("opposite", "one")),
                        "sag": 0.6, "thin": 0.07}),
    ("sink", lambda r: {"depth": 0.6}),
    ("fold", lambda r: {"folds": 3, "pitch": 0.9}),
    ("vault", lambda r: {"rise": 1.2, "bays": r.choice((1, 5))}),
    ("interlock", lambda r: {"bite": 0.75, "size": 0.5, "reach": 0.55}),
    ("branch", lambda r: {"n": 3, "reach": 0.55, "height": 0.6}),
)


_SAYS = {
    "extrude": "a single body", "loop": "a ring around a court",
    "aggregate": "a field of small bodies", "stack": "stacked tiers",
    "compress": "narrowed to a bar", "gable": "under a pitched roof",
    "vault": "under a barrel vault", "fold": "under a folded roof",
    "butterfly": "under a butterfly roof", "mansard": "under a mansard",
    "grade": "its top graded down toward the open side",
    "lift": "lifted clear of the ground on supports",
    "carve": "carved open", "split": "split in two",
    "taper": "tapering as it rises", "twist": "turning as it rises",
    "stagger": "staggered along its length",
    "shear": "raked back by one oblique plane", "notch": "notched at a corner",
    "puncture": "punctured through", "inscribe": "with an inscribed court",
    "nest": "with a nested body set proud", "cantilever": "cantilevered toward the open side",
    "canopy": "under a canopy", "pinch": "pinched at the waist",
    "bend": "bent along its length", "expand": "widening as it rises",
    "roof": "under a warped roof plate with a flying eave",
    "sink": "set down into the ground",
}


def _caption(ops: list) -> str:
    parts = [_SAYS.get(op["op"], op["op"]) for op in ops]
    if ops and ops[0]["op"] == "grade" and ops[0].get("walk"):
        parts[0] = "a walkable landscape roof"
    walk = any(op["op"] == "grade" and op.get("walk") for op in ops)
    body = parts[0]
    rest = ", ".join(parts[1:])
    line = f"{body}, {rest}" if rest else body
    if walk:
        line += "; the slope is public ground"
    return line[0].upper() + line[1:] + "."


_WHY = ("swept from the grammar - the funnel, not this sentence, argues; "
        "gates and juries decide what survives")


# A move that leaves the body's own outline needs ground to move onto: said
# on a parcel-filling extrusion the legal line takes all of it and the whole
# sentence is dropped as clipped (audit A/B, 09-03).
_NEEDS_ROOM = frozenset({
    "expand", "offset", "shift", "stagger", "skew", "cantilever", "canopy",
    "lodge", "extract", "nest", "branch", "embed", "intersect", "inscribe",
    "interlock", "overlap", "roof",
})
# A move that translates or scales the WHOLE composition says nothing the
# pipeline keeps: the siting re-seats it and the fit rescales it, so the
# building comes back the same. Scoped to one part of a split body it is a
# relation between two bodies, and it survives (audit C).
_NEEDS_PART = frozenset({"expand", "offset", "shift"})
_ROOM = {"op": "compress", "ratio": 0.66, "toward": "cross"}
_PART = {"op": "split", "ratio": 0.45, "gap": 0}


def _sentence(r: random.Random, index: int, extreme: bool = False,
              prefix: str = "sweep") -> dict:
    openers = _EXTREME_OPENERS if extreme else _OPENERS
    mods = _EXTREME_MODS if extreme else _MODS
    opener, oparams = r.choice(openers)
    ops = [{"op": opener, **oparams(r), "why": _WHY}]
    # Extreme: exactly ONE dominant move (plus an optional bar-maker so a
    # ridge/shear has a long axis to speak on). Mid: 1-3 mods as before.
    if extreme:
        if r.random() < 0.4:
            ops.append({"op": "compress", "ratio": 0.6, "toward": "cross", "why": _WHY})
        verb, vparams = r.choice(mods)
        ops.append({"op": verb, **vparams(r), "why": _WHY})
    else:
        for _ in range(r.choice((1, 1, 2, 2, 3))):
            verb, vparams = r.choice(mods)
            if any(o["op"] == verb for o in ops):
                continue
            ops.append({"op": verb, **vparams(r), "why": _WHY})
    # The audit's two rules, applied where the sentence is assembled.
    said = {op["op"] for op in ops}
    if said & _NEEDS_ROOM and "compress" not in said and opener == "extrude":
        ops.insert(1, {**_ROOM, "why": _WHY})
    if said & _NEEDS_PART:
        if "split" not in {op["op"] for op in ops}:
            # Immediately BEFORE the scoped verb, not second-to-last: the mods
            # are drawn in random order, so inserting by position left the
            # verb naming a `part_b` that did not exist yet - an `on` that
            # names nothing, which the validator refuses.
            first = next(index for index, op in enumerate(ops)
                         if op["op"] in _NEEDS_PART)
            ops.insert(first, {**_PART, "why": _WHY})
        for op in ops:
            if op["op"] in _NEEDS_PART:
                op["on"] = "part_b"
    return {
        "name": f"{prefix}_{index:04d}_{opener}_{'_'.join(o['op'] for o in ops[1:]) or 'pure'}",
        "primary_language": "solid_body" if opener != "loop" else "open_figure",
        "secondary_language": "generated sweep candidate - see name for the verbs",
        "formal_principle": _caption(ops),
        "dominant_gesture": ops[-1]["op"],
        "reference_basis": "grammar sweep",
        "floor_height_m": 3.4,
        "ops": ops,
    }


def main() -> int:
    count = int(sys.argv[1])
    out = Path(sys.argv[2])
    seed = int(sys.argv[3]) if len(sys.argv) > 3 else 20260902
    extreme = "--extreme" in sys.argv
    r = random.Random(seed)
    # Names carry the book's stem so two books never share a sentence name
    # (corpus loaders read every runs/sweeps/*.json; sweep01/sweep03 once
    # both minted sweep_0067_loop_mansard).
    prefix = out.stem

    # The validator is the correctness owner: generate, filter by its
    # check() (which derives verbs/params from the executor source), repeat.
    import backend.app.modules.massing.workspace_tools.validate_authored as va

    out.parent.mkdir(parents=True, exist_ok=True)
    probe = out.parent / "_sweep_probe.json"
    # The validator refuses a book that holds the same idea twice, but each
    # draw is checked alone in its probe, so a sweep could keep two sentences
    # of one family and spend two of its seats on one idea - 16 kept, 14
    # families, measured. Same key the validator and the curator use:
    # (opener, dominant move family, stature band).
    from backend.app.modules.design.generation.maas.massv2.family import family_key  # noqa: E402
    kept: list[dict] = []
    families: set = set()
    same_idea = 0
    tried = 0
    while len(kept) < count and tried < count * 8:
        tried += 1
        record = _sentence(r, tried, extreme=extreme, prefix=prefix)
        probe.write_text(json.dumps({"schemes": [record]}, ensure_ascii=False),
                         encoding="utf-8")
        faults, _verbs, _profiles = va.check(probe)
        if faults:
            continue
        key = family_key(record)
        if key in families:
            same_idea += 1
            continue
        families.add(key)
        kept.append(record)
    probe.unlink(missing_ok=True)
    out.write_text(json.dumps({"schemes": kept}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"kept {len(kept)} / tried {tried} (seed {seed}, "
          f"{same_idea} same-family draws skipped) -> {out}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
