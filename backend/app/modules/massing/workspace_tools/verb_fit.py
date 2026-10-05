"""Which sentences use verbs that cannot say what they claim.

Four of these were found one at a time by looking at drawings, and each cost a
round trip: `gable` (a prism language has no pitched roof), CCTV's `loop` (rings
a court in plan, cannot stand one up), CopenHill's `taper` (narrows on every
side, so it builds a ziggurat rather than a one-way slope), and Sendai's `carve`
(reaches in from an edge, so it makes a recess rather than a tube).

They share a shape, and it is the one no gate can see: every word does change the
mass, so the diff check passes, the gap check passes, the physics passes - and
the mass is simply not what the caption says. `sentence-contradicted` was the
critics' most frequent fault by count, and this is where it comes from.

So this reads the principle and the gesture as text and asks which verbs could
possibly carry the claim. It is a screen and not a verdict: a hit means go and
look, and the rule that applies is the one this package has learned four times -
measure before changing anything, because two of the four candidates it flags on
the current corpus turn out to be arguable.

    python tmp_mass_check/_massv2/tools/verb_fit.py
"""

from backend.app.modules.massing import paths as _mass_paths
from backend.app.modules.design.generation import paths as _design_paths
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime


import json
import re
import sys
from pathlib import Path

INPUTS = _mass_paths.workspace_root() / 'inputs'

# (label, what the sentence says, which verbs can build it)
# An empty verb set means this grammar cannot say it at all.
RULES = [
    ("한방향 경사", r"\b(slope|sloping|ramp|ramps)\b|경사|내려온다|\bdescends?\b",
     {"grade", "skew"}),
    # carve belongs here since `through: true` - it opens both ends and bores.
    # The screen cannot see params, so a through-less carve claiming 관통 will
    # pass this rule; that is the screen being a screen.
    ("관통 구멍", r"\b(tube|tubes|pierced|pierces)\b|관통|light well",
     {"puncture", "intersect", "carve"}),
    ("공중/캔틸레버", r"\b(cantilever|cantilevers|floats)\b|받치는 것들보다|"
     r"does not touch|passes under|아래 지면이", {"lift", "carve"}),
    # ⚠️ Both Seattle sentences hit this rule and both are false positives,
    # settled by measuring rather than by argument. Their "사이" is not a gap
    # in plan, it is the space under the plates their shear already builds:
    # `shifted_past_each_other` overhangs 930 m² at 4.8 m of clearance, 427 at
    # 7.2 and 165 at 9.6; `moved_nine_tenths` has two tiers overhanging 100% -
    # they do not rest on the tier below at all. Every one of those clearances
    # is far past the 2.4 m this package calls a room. A shear can build a
    # between-space, so it belongs in the set.
    # "told apart" and "tell apart" mean distinguished, not standing apart -
    # Richards' towers are told apart in the massing and attached to their
    # spine, and the bare \bapart\b flagged the idiom. Same trap family as
    # `ring` inside "bring", recorded at the bottom of this file.
    ("떨어져 섬", r"\b(?<!told )(?<!tell )apart\b|\bseparate\b|streets between|between them|사이가|사이로|떨어져",
     {"split", "aggregate", "loop", "stagger", "branch"}),
    # 박공 is sayable now - two wedges meeting at a ridge, real planes since
    # `top_drop` entered the IR. Vaults still are not: no curved-section term.
    ("지붕 형태", r"\b(gable|gabled|pitched|ridge)\b|박공", {"gable"}),
    ("볼트 지붕", r"\b(vault|vaults|vaulted)\b|볼트|roof that narrows", set()),
    ("틀어짐", r"\b(askew|rotated|rotates)\b|at an angle|틀어|각을",
     {"rotate", "twist", "skew"}),
    ("둘러쌈/고리", r"\b(ring|loop|encircles|wraps)\b|고리|둘러", {"loop", "carve"}),
]


def sweep() -> list[tuple]:
    rows = []
    for path in sorted(INPUTS.glob("gen-*.json")):
        for scheme in json.loads(path.read_text(encoding="utf-8"))["schemes"]:
            # The principle only. `dominant_gesture` describes the reference
            # building - what it looks like in photographs - while the principle
            # is what this mass has to do. Reading both flagged all three of
            # `oma_netherlands_dance_theatre`, `oma_snu_museum_of_art` and
            # `kunsthal_a_ramp_is_the_building` for slopes and tunnels that
            # appear only in the description of the original: Dance Theatre's
            # claim is three bodies tied by one floor, which its `aggregate` and
            # `tie` build exactly, and SNU's is one core with two unequal arms,
            # which its `split` and `lift` build exactly.
            said = scheme.get("formal_principle", "").lower()
            used = {op["op"] for op in scheme["ops"]}
            for label, pattern, buildable in RULES:
                hit = re.search(pattern, said)
                if not hit:
                    continue
                if not buildable:
                    rows.append((label, scheme["name"], "표현 불가", hit.group(0), used))
                elif not (buildable & used):
                    rows.append((label, scheme["name"], "동사 없음", hit.group(0), used))
    return sorted(rows)


def main() -> int:
    rows = sweep()
    print("%-12s %-38s %-9s %-16s %s" % ("개념", "scheme", "판정", "걸린 말", "쓰인 동사"))
    for label, name, verdict, word, used in rows:
        print("%-12s %-38s %-9s %-16s %s" % (
            label, name[:38], verdict, word[:16], ",".join(sorted(used))[:38]
        ))
    print()
    print("후보 %d 건" % len(rows))
    # ⚠️ Word boundaries matter. The first version of this matched `ring` inside
    # "bring" and "narrowing" and produced three false hits out of twelve.
    return 0


if __name__ == "__main__":
    sys.exit(main())
