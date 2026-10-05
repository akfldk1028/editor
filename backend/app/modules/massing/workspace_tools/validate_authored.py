"""Check authored sentences against the grammar before the pipeline sees them.

A generator plus a sound verifier is the part of LLM-Modulo that pays; the
critique loop is the part that does not. So this refuses, it does not advise.
"""

from backend.app.modules.massing import paths as _mass_paths
from backend.app.modules.design.generation import paths as _design_paths
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime


import inspect
import json
import re
import sys
from collections import Counter
from pathlib import Path

from backend.app.modules.design.generation.maas.massv2.grammar import BASE_ORIENTATIONS, BASE_VOLUME_LABELS, STACK_CONTRAST_RANGE

# The verb list drifted from the executor twice: once an authoring agent hit
# a `tie` floor the executor no longer had, and once this file refused seven
# real words (gable, vault, canopy, lodge, nest, branch, mansard) and the
# whole stack-method parameter set - a hand-copied enumeration is exactly
# what the one-owner rule exists to prevent. So the owner answers directly:
# verbs come from `execute._VERBS`, and each verb's parameters are read out
# of its own source (`op.params.get("...")`). The old hand table survives
# only as a union for helpers this scan cannot see into.
_HAND_PARAMS = {
    "extrude":   {"height"},
    "split":     {"ratio", "along", "first", "second", "contrast", "gap"},
    "stack":     {"n", "contrast", "align", "height", "grow"},
    "aggregate": {"n", "spread", "height", "tie"},
    "loop":      {"bar", "height", "step"},
    "stagger":   {"ratio", "toward"},
    # The BOOK's Shear (p.32) is one oblique plane through the body, and its
    # page carries one variation parameter. `side` names which flank it rakes.
    "shear":     {"angle", "toward", "side"},
    "taper":     {"ratio"},
    "lift":      {"clearance"},
    "carve":     {"size", "at", "reach"},
    "notch":     {"size", "at"},
    "puncture":  {"size", "n"},
    "rotate":    {"degrees"}, "skew": {"degrees", "toward"},
    # The affine table's verbs are lambdas taking `p`, so the `params.get`
    # scan below never sees their names. `shift`, `shear` and the rest are
    # listed here for that reason and `sink` was missed when it was added -
    # the sweep could not say "into the ground" at all.
    "sink":      {"depth"},
    "twist":     {"degrees"}, "shift": {"ratio", "toward"},
    "offset":    {"ratio", "toward"}, "expand": {"ratio", "toward"},
    "compress":  {"ratio", "toward"}, "inflate": {"ratio"},
}
# Read by the frame, the parser or the grid on ANY op: target, regulating
# pivot, plan family, declared stature (the grid stamps `storeys` as
# declared stature whatever the verb - the declared-storeys exemption).
_UNIVERSAL = {"on", "about", "profile", "storeys"}


def _derived_verbs() -> tuple[dict, dict]:
    from backend.app.modules.design.generation.maas.massv2.execute import _VERBS
    table, numeric = {}, {}
    for verb, fn in _VERBS.items():
        try:
            source = inspect.getsource(fn)
        except (OSError, TypeError):
            source = ""
        params = set(re.findall(r'params\.get\(\s*"([a-z_]+)"', source))
        table[verb] = params | _HAND_PARAMS.get(verb, set()) | _UNIVERSAL
        # A parameter the executor reads through float() is a number. comp27's
        # author wrote `inscribe across: "court"`, the range check only looks
        # at values that already are numbers, and the executor crashed the
        # whole run of 246 on that one word.
        numeric[verb] = set(re.findall(r'float\(\s*op\.params\.get\(\s*"([a-z_]+)"', source)) | set(RANGES_KEYS)
    return table, numeric


RANGES_KEYS = ("ratio", "size", "depth", "reach", "clearance", "degrees", "n", "spread", "contrast", "gap", "rise")  # `at` is a side name for carve/notch
VERBS, NUMERIC = _derived_verbs()
PROFILES = {"square", "oval", "stadium", "hexagon", "chamfered", "faceted",
            "trapezoidal", "triangular", "kite", "concave_l"}
LANGUAGES = {"solid_body", "carved_body", "open_figure", "porous_field"}
RANGES = {
    "height": (0.1, 1.0), "ratio": (0.15, 0.95), "n": (2, 6),
    "contrast": (1.2, 2.5), "spread": (1.2, 2.5), "bar": (0.15, 0.5),
    # 0 is legal and means "no binding plate at all" - Moriyama and the
    # Inujima Art Houses have none, and the executor allows it since the
    # field cap was lifted. The validator was still refusing it.
    "tie": (0.0, 0.4), "step": (0.4, 1.0),
    "size": (0.1, 0.7), "reach": (0.0, 1.0), "clearance": (0.1, 0.4),
    "degrees": (-90.0, 90.0),
    # `gap` is a multiplier of JOINT_CLEARANCE_M (0.76 m) and the executor
    # does not clamp it. 9 is 6.8 m, which is a courtyard between two bodies
    # rather than a construction tolerance - the void the critics said the
    # corpus never produces. Bounded only where the parts would leave the site.
    "gap": (0.0, 12.0),
    "sag": (0.0, 0.6),
}
CROWN_FORMS = {"dome", "dish", "saddle"}

# A stack tapers by `contrast` per tier, so its top tier is 1/contrast^(n-1)
# of its base. At n=6, contrast=2.5 that is 1.0% - on this parcel a 5 m2
# sliver, which the compiler drops as debris and the plausibility gate calls
# a shard. Fifty-five corpus sentences declare a stack like that, and their
# roof words then land on nothing: `wild01_0071_stack_vault` puts five vault
# bays on a 0.3 m2 top tier and delivers five flat boxes, which is why a
# sheet of different sentences reads as one block repeated.
#
# The floor is the delivery gate's own crumb share (plausibility
# CRUMB_MASS_SHARE = 0.04): a tier the mass would throw away is a tier the
# sentence may not declare.
STACK_TOP_TIER_MIN_SHARE = 0.04


def _vanishing_stacks(schemes: list) -> list[str]:
    """Sentences whose stack tapers its top tier away to debris."""

    faults = []
    for scheme in schemes:
        for index, op in enumerate(scheme.get("ops") or ()):
            if str(op.get("op")) != "stack":
                continue
            try:
                tiers = int(op.get("n") or 0)
                contrast = float(op.get("contrast") or 1.0)
            except (TypeError, ValueError):
                continue
            if tiers < 2 or contrast <= 1.0:
                continue
            top = 1.0 / (contrast ** (tiers - 1))
            if top < STACK_TOP_TIER_MIN_SHARE:
                faults.append(
                    f"{scheme.get('name')} op{index} (stack): n={tiers} with "
                    f"contrast={contrast} leaves the top tier at {top:.1%} of the "
                    f"base - under the {STACK_TOP_TIER_MIN_SHARE:.0%} crumb share the "
                    f"delivery throws away, so anything said about the top is lost"
                )
    return faults

# Where a parameter name means different things to different verbs. `ratio` is
# a share for `split` and a multiplier for `expand`, so one global range refused
# a legal `expand: 1.6`. Checked before RANGES.
PER_VERB_RANGES = {
    # `n` counts different things: puncture clamps 1..3, stack 2..6, and a
    # field 2..MAX_FIELD_OBJECTS (12). One global (2, 6) refused a legal
    # single puncture and every field of seven or more - the extreme
    # sweep's n 7-9 openers never entered a book, silently. These mirror
    # the executor's own clamps (execute.py: _puncture, _stack, _aggregate).
    ("puncture", "n"): (1, 3),
    ("stack", "n"): (2, 6),
    ("aggregate", "n"): (2, 12),
    # `step` counts different things too. `loop` steps a ring's bars inside
    # the figure and clamps 0.4..1.0; `array` steps a copy PAST the one before
    # it, so anything at or under 1.0 overlaps and the run reads as one long
    # body. Measured on comp18: an authored 0.85 - inside the advertised range
    # - was raised to 1.05 on delivery without a word, and the `join` written
    # to bridge the courts between the copies found no gap and was reported
    # silent. These mirror `ops.aggregation.array` and `execute._loop`.
    ("array", "step"): (1.05, 2.0),
    ("array", "n"): (2, 6),
    ("pack", "n"): (2, 9),
    ("pack", "fill"): (0.3, 0.9),
    ("reflect", "clear"): (1.0, 1.6),
    ("join", "size"): (0.1, 0.5),
    ("join", "level"): (0.0, 0.6),
    ("shear", "angle"): (5.0, 45.0),
    # Where the executor clamps tighter than the global range, a value the
    # validator accepts is rewritten on delivery without a word: split
    # 0.3..0.75, loop bar to 0.4, carve size 0.15..0.6, cantilever reach
    # to 0.6. The validator now says so instead.
    ("split", "ratio"): (0.3, 0.75),
    ("loop", "bar"): (0.15, 0.4),
    ("carve", "size"): (0.15, 0.6),
    ("notch", "size"): (0.15, 0.5),
    ("puncture", "size"): (0.1, 0.45),
    # cantilever's OWN clamp (swept.py): MIN_OFFSET_RATIO .. 0.65*1.6/2.6;
    # the 0.0..0.6 first written here was aggregate's reach.
    ("cantilever", "reach"): (0.15, 0.4),
    ("expand", "ratio"): (1.0, 1.6),
    ("inflate", "ratio"): (1.0, 1.6),
    ("compress", "ratio"): (0.6, 1.0),
    ("stack", "contrast"): STACK_CONTRAST_RANGE,
    ("split", "contrast"): (1.2, 3.5),
    ("aggregate", "spread"): (1.05, 2.5),
}

# Verbs that bring volumes into being. Everything else transforms or cuts what
# is already standing, so a sentence that opens with one of those has nothing to
# act on and produces no mass at all - the diff check reports an empty list
# rather than a silent word, which is easy to miss.
MAKING_VERBS = {"extrude", "stack", "loop", "aggregate"}

REQUIRED = ("name", "primary_language", "secondary_language", "formal_principle",
            "dominant_gesture", "reference_basis", "ops")

# The opening. The BOOK's grammar is three parts and the first is choosing what
# to act on - a relative base volume and the axis that carries the fraction -
# and this validator did not know the keys existed, so neither did the brief it
# derives: 901 of 901 authored sentences opened on the silent default and every
# mass began as the whole parcel. The enums come from the executor's own table,
# so they cannot drift from what the parser will accept.
def _as_fraction(label: str) -> float:
    top, _, bottom = str(label).partition("/")
    try:
        return float(top) / float(bottom or 1.0)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


OPENING = {
    # Largest first, so the brief reads down from the whole parcel rather than
    # in the string order that puts 1/16 second.
    "base_volume": sorted(BASE_VOLUME_LABELS, key=_as_fraction, reverse=True),
    "base_orientation": sorted(BASE_ORIENTATIONS),
}


def _source_value(value):
    """Hashable JSON content: object order is irrelevant, operation order is not.

    Python number equality preserves integer/float equivalence without rounding
    real geometric parameters; booleans remain different from numbers.
    """
    if isinstance(value, dict):
        return ('object', tuple(sorted((key, _source_value(item)) for key, item in value.items())))
    if isinstance(value, (list, tuple)):
        return ('array', tuple(_source_value(item) for item in value))
    if isinstance(value, bool):
        return ('boolean', value)
    if isinstance(value, (int, float)):
        return ('number', value)
    if value is None or isinstance(value, str):
        return (type(value).__name__, value)
    raise TypeError('An authored source must contain JSON values')


def _repeated_families(schemes: list) -> list[str]:
    """Refuse duplicate executable sources, not a coarse curator family.

    The historical function name is retained for callers. Bend and twist, or
    different profiles/roof surfaces, may share opener/dominant/stature. That
    partition is not evidence of identical geometry. Parse with the grammar
    owner and compare the complete executable definition, excluding prose.
    This is conservative source deduplication; actual geometric equivalence
    and fit remain the downstream delivery/selection owners' responsibility.
    """
    from backend.app.modules.design.generation.maas.massv2.grammar import parti_from_record, PLOT_MODES

    seen: dict[tuple, str] = {}
    faults: list[str] = []
    for scheme in schemes:
        try:
            # Do not turn a partly parsed invalid source into a duplicate of a
            # valid one. Unknown words are reported by the existing validator.
            if any(str(op.get('op') or '').strip() not in PLOT_MODES for op in scheme.get('ops') or ()):
                continue
            parti = parti_from_record(scheme)
            if parti is None:
                continue
            key = _source_value({
                'operations': [(op.verb, op.plot_mode, op.params) for op in parti.ops],
                'floor_height_m': parti.floor_height_m,
                'growth': parti.growth,
                'primary_language': parti.primary_language,
            })
        except Exception:  # noqa: BLE001 - a malformed scheme is another fault
            continue
        first = seen.get(key)
        if first is not None:
            faults.append(
                f"{scheme.get('name')}: repeats the executable source of {first} "
                f"(same ordered operations, parameters and execution contract); "
                f"changing a title or explanation does not create another source"
            )
            continue
        seen[key] = str(scheme.get("name"))
    return faults


# The words that change a mass's section or its relation to the ground -
# under a storey cap, the only place diversity can come from. Derived from
# the executor's verb table so a new word (crown) counts the day it exists.
SECTION_WORDS = {"gable", "butterfly", "mansard", "vault", "fold", "roof", "crown", "grade",
                 "canopy", "sink", "lift", "cantilever", "carve", "puncture", "inscribe",
                 "notch", "taper", "pinch", "twist"} & set(VERBS)
COVERAGE_MIN_BOOK = 6          # a book this size is a round; smaller books are probes
COVERAGE_MIN_OPENERS = 2
COVERAGE_MIN_SECTION_WORDS = 3
COVERAGE_MIN_PROFILES = 2


def _thin_coverage(schemes: list) -> list[str]:
    """A round-sized book that leaves most of the language unsaid.

    Openers (extrude/loop/aggregate/stack) set the part-to-whole; section and
    ground words set the silhouette a storey cap cannot flatten; plan
    profiles set the figure. A book of six with one opener, one section word
    and one profile is six of the same building, however different the
    parameters.
    """

    if len(schemes) < COVERAGE_MIN_BOOK:
        return []
    openers, words, profiles = set(), set(), set()
    for scheme in schemes:
        ops = scheme.get("ops") or []
        if ops:
            openers.add(str(ops[0].get("op")))
        for op in ops:
            verb = str(op.get("op"))
            if verb in SECTION_WORDS:
                words.add(verb)
            if op.get("profile"):
                profiles.add(str(op["profile"]))
    faults = []
    if len(openers) < COVERAGE_MIN_OPENERS:
        faults.append(f"book: {len(schemes)} sentences open with {sorted(openers)} only - "
                      f"use at least {COVERAGE_MIN_OPENERS} openers (extrude/loop/aggregate/stack)")
    if len(words) < COVERAGE_MIN_SECTION_WORDS:
        faults.append(f"book: {len(schemes)} sentences use section/ground words {sorted(words)} only - "
                      f"use at least {COVERAGE_MIN_SECTION_WORDS} distinct ones of {sorted(SECTION_WORDS)}")
    if len(profiles) < COVERAGE_MIN_PROFILES:
        faults.append(f"book: {len(schemes)} sentences draw profiles {sorted(profiles)} only - "
                      f"use at least {COVERAGE_MIN_PROFILES} of {sorted(PROFILES)}")
    return faults


def check(path: Path) -> tuple[list, Counter, Counter]:
    faults: list[str] = []
    verbs: Counter = Counter()
    profiles: Counter = Counter()
    data = json.loads(path.read_text(encoding="utf-8"))
    schemes = data.get("schemes")
    if not isinstance(schemes, list) or not schemes:
        return [f"{path.name}: no schemes"], verbs, profiles

    for scheme in schemes:
        name = scheme.get("name", "?")
        from backend.app.modules.design.generation.maas.massv2.grammar import mistyped_words
        for verb, key, value in mistyped_words(scheme):
            faults.append(f"{name} {verb}: invalid {key}={value}")
        for field in REQUIRED:
            if not scheme.get(field):
                faults.append(f"{name}: missing {field}")
        for field, allowed in OPENING.items():
            said = scheme.get(field)
            # Declaring the opening is optional - 952 sentences were written
            # before it existed and they still mean what they meant. Saying it
            # wrong is not: `parti_from_record` drops a label it does not know
            # and the sentence silently opens on the whole parcel instead.
            if said is not None and str(said) not in allowed:
                faults.append(f"{name}: {field} {said!r} not one of {allowed}")
        if scheme.get("primary_language") not in LANGUAGES:
            faults.append(f"{name}: primary_language {scheme.get('primary_language')!r} "
                          f"not one of {sorted(LANGUAGES)}")
        ops = scheme.get("ops") or []
        if ops and str(ops[0].get("op")) not in MAKING_VERBS:
            faults.append(f"{name}: opens with {ops[0].get('op')!r}, which needs a "
                          f"volume to act on - start with one of {sorted(MAKING_VERBS)}")
        # The floor was 2 and it outlawed the canon: a pure cylinder or a
        # single wide slab IS one statement, and demanding a second verb is
        # how every mass in the pool grew at least one extra move - the
        # client's "정갈하지 않다" traced back to this line.
        if not 1 <= len(ops) <= 6:
            faults.append(f"{name}: {len(ops)} ops, wanted 1..6")

        # what names exist for a later verb to aim at
        available: set[str] = set()
        for index, op in enumerate(ops):
            verb = op.get("op")
            if verb not in VERBS:
                faults.append(f"{name} op{index}: unknown verb {verb!r}")
                continue
            verbs[verb] += 1
            unknown = set(op) - VERBS[verb] - {"op", "why"}
            if unknown:
                faults.append(f"{name} op{index} ({verb}): unknown params {sorted(unknown)}")
            if not str(op.get("why") or "").strip():
                faults.append(f"{name} op{index} ({verb}): no why")
            for key in NUMERIC.get(verb, ()):
                value = op.get(key)
                if key in op and (isinstance(value, bool) or not isinstance(value, (int, float))):
                    faults.append(f"{name} op{index} ({verb}): {key} must be a number, got {value!r}")
            for key, (lo, hi) in RANGES.items():
                if key in op and isinstance(op[key], (int, float)):
                    lo, hi = PER_VERB_RANGES.get((verb, key), (lo, hi))
                    if (verb, key) == ("aggregate", "spread") and \
                            str(op.get("method") or "") == "stack":
                        # The stack branch uses spread as its size fan and
                        # 1.0 (no fan) is legal there; the 1.05 floor is the
                        # pack branch's spacing rule.
                        lo = 1.0
                    if not lo <= op[key] <= hi:
                        faults.append(f"{name} op{index} ({verb}): {key}={op[key]} "
                                      f"outside {lo}..{hi}")
            if verb == "crown" and str(op.get("form") or "dome") not in CROWN_FORMS:
                faults.append(f"{name} op{index}: crown form {op.get('form')!r} unknown "
                              f"(one of {sorted(CROWN_FORMS)})")
            if "profile" in op:
                if op["profile"] not in PROFILES:
                    faults.append(f"{name} op{index}: profile {op['profile']!r} unknown")
                else:
                    profiles[op["profile"]] += 1
            # an `on` that names nothing is a silent verb by construction
            target = str(op.get("on") or "").strip()
            if target and not any(known.startswith(target) or target.startswith(known)
                                  for known in available):
                faults.append(f"{name} op{index} ({verb}): on={target!r} names nothing "
                              f"standing (available: {sorted(available) or 'nothing yet'})")
            if verb == "split":
                available.update({str(op.get("first") or "part_a"),
                                  str(op.get("second") or "part_b")})
            elif verb == "extrude":
                available.add("body")
            elif verb == "stack":
                available.update(f"tier_{i}" for i in range(int(op.get("n", 3))))
            elif verb == "aggregate":
                available.update(f"object_{i}" for i in range(int(op.get("n", 4))))
                available.add("field_plate")
            elif verb == "loop":
                available.update({"bar_n", "bar_s", "bar_e", "bar_w"})
            elif verb == "lift":
                available.add("support")
    faults.extend(_repeated_families(schemes))
    faults.extend(_thin_coverage(schemes))
    faults.extend(_vanishing_stacks(schemes))
    return faults, verbs, profiles


def main() -> None:
    total_faults = 0
    verbs: Counter = Counter()
    profiles: Counter = Counter()
    count = 0
    for arg in sys.argv[1:]:
        path = Path(arg)
        if not path.exists():
            print(f"MISSING  {path}")
            total_faults += 1
            continue
        faults, v, p = check(path)
        verbs += v
        profiles += p
        count += len(json.loads(path.read_text(encoding="utf-8")).get("schemes", []))
        status = "OK" if not faults else f"{len(faults)} FAULTS"
        print(f"\n=== {path.name}: {status}")
        for fault in faults[:40]:
            print("   ", fault)
        total_faults += len(faults)
    print(f"\nsentences {count}   faults {total_faults}")
    print("verbs   ", dict(verbs.most_common()))
    print("profiles", dict(profiles.most_common()))
    carve = verbs.get("carve", 0)
    if count:
        print(f"carve per sentence: {carve/count:.2f}   (기존 코퍼스 0.97)")
    sys.exit(1 if total_faults else 0)


if __name__ == "__main__":
    main()
