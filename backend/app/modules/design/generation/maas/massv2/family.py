"""The composition family of a sentence, computed instead of eyeballed.

Three times in one day a board was curated by hand because near-identical
partis stacked up - six plinth-and-turned-tower schemes side by side, from
three authors who were told to be different. Personas do not partition a
model's distribution; a key does. This module owns the question "are these
two sentences the same building?" at the level a jury reads - physical
principle, not detail - so staging, boards and the cell selector can prefer
one-per-family without anyone looking.

Born as a workspace tool beside the board curator; moved here the day the
audit showed the delivered thirty-two picks were fifteen families, one of
them seated six times - the selector deduped by sentence NAME, and a family
is exactly what a set of names has in common.

The key is (opener, move families, stature band): which word stands the
volume up, which *kinds* of moves act on it (not their parameters), and
whether the body is low, mid or tall. plinth_turned_tower, grid_realigned
_tower and plinth_slender_turned all collapse to (extrude, relational, low)
- which is exactly what both judges said of them.
"""

from collections import Counter
from itertools import groupby
import json


# Reference geometry for the metric executor, not a size acceptance cutoff.
# Family keys retain topology and variation kinds, never measured dimensions.
SHAPE_FAMILY_REFERENCE_SPAN_M = 100.0


def _surface_family(surface, region, vertical_sign=1):
    """Variation over the actual authored region, independent of coefficients."""
    from shapely import affinity
    from backend.app.modules.design.generation.maas.source_geometry.ir import profile_height
    from backend.app.modules.design.generation.maas.source_geometry.solid import AffineSurface, ConstantSurface, PolynomialSurface, ProfileSurface, surface_bounds
    if surface is None or isinstance(surface, ConstantSurface):
        return 'flat'
    if isinstance(surface, AffineSurface):
        if surface.scale == 0:
            return 'flat'
        return _surface_family(surface.surface,
            affinity.affine_transform(region, surface.world_to_authored),
            vertical_sign*(1 if surface.scale > 0 else -1))
    low, high = surface_bounds(surface, region.bounds)
    if low == high:
        return 'flat'
    if isinstance(surface, ProfileSurface):
        span = surface.span[1]-surface.span[0]
        stations = [min(1., max(0., (x*surface.axis[0]+y*surface.axis[1]-surface.span[0])/span))
                    for x, y in region.exterior.coords]
        left, right = min(stations), max(stations)
        samples = sorted({left, right} | {u for u, _ in surface.points if left < u < right})
        heights = [vertical_sign*profile_height(surface.points, u) for u in samples]
        signs = tuple(k for k, _ in groupby((b > a)-(b < a) for a, b in zip(heights, heights[1:])))
        if not signs or signs == (0,):
            return 'flat'
        if len(signs) == 1:
            return 'slope'
        # Reversing the horizontal direction preserves ridge/valley identity.
        signs = min(signs, tuple(-s for s in reversed(signs)))
        return 'profile:'+','.join(map(str, signs))
    if isinstance(surface, PolynomialSurface):
        terms = {}
        for x, y, coefficient in surface.terms:
            terms[x, y] = terms.get((x, y), 0)+coefficient*vertical_sign
        powers = sorted((x, y, 1 if c > 0 else -1) for (x, y), c in terms.items() if c != 0 and x+y > 0)
        if not powers:
            return 'flat'
        if max(x+y for x, y, _ in powers) == 1:
            return 'slope'
        powers = min(powers, sorted((y, x, sign) for x, y, sign in powers))
        return 'polynomial:'+json.dumps(powers, separators=(',', ':'))
    raise ValueError('unsupported bounded surface family')


def shape_family_evidence(scheme: dict) -> dict:
    """Read a neutral execution through existing geometry owners; no site fit.

    This describes authored topology, not site feasibility or a similarity
    distance. The current surface approximation/boolean policies remain owned
    by the executor and compiler; no family-area or feature-size threshold is
    introduced. Invalid/unexecutable shapes have one unresolved descriptor.
    """
    from shapely.geometry import Polygon, box
    from shapely.ops import unary_union
    from backend.app.modules.design.generation.maas.source_geometry.solid import polygons
    from backend.app.modules.design.generation.maas.massv2.compile import compile_matrix_form
    from backend.app.modules.design.generation.maas.massv2.execute import execute
    from backend.app.modules.design.generation.maas.massv2.grammar import parti_from_record
    from backend.app.modules.design.generation.maas.massv2.profiles import unit_plan
    reference = SHAPE_FAMILY_REFERENCE_SPAN_M
    try:
        form = execute(parti_from_record(scheme), buildable=box(0, 0, reference, reference),
                       axis=(1., 0.), height_m=reference)
        if form is None:
            raise ValueError('neutral execution produced no material')
        source = compile_matrix_form(form, storey_height_m=0.)
        if source is None:
            raise ValueError('neutral compilation produced no material')
        projection = unary_union([v.footprint for v in source.volumes])
        plans = sorted((len(p.interiors), p.equals(p.convex_hull)) for p in polygons(projection))
        sections = set()
        for item in form.additive():
            region = item.plan_region if item.plan_region is not None else Polygon(unit_plan(item.plan))
            top = _surface_family(item.top_surface, region)
            bottom = _surface_family(item.bottom_surface, region)
            if item.top_surface is None and item.top_drop > 0:
                # A legacy roof may coexist with typed plans. Keep its existing
                # section vocabulary instead of pretending the top is flat.
                top = ('warp' if item.warp is not None else 'profile' if item.top_profile is not None
                       else 'gable' if item.ridge_along is not None else 'slope')
            if top != 'flat' or bottom != 'flat':
                sections.add((top, bottom))
        return {'status': 'measured', 'basis': 'neutral_execute_and_source_geometry',
                'reference_span_m': reference, 'plan_components': plans,
                'sections': sorted(sections)}
    except (ValueError, TypeError, KeyError, AttributeError, IndexError) as exc:
        return {'status': 'unresolved', 'basis': 'neutral_execute_and_source_geometry',
                'reference_span_m': reference, 'error_type': type(exc).__name__}


def _stack_level_organization(scheme):
    """Count executed occupied units per base elevation; no copied stack rules."""
    from shapely.geometry import box
    from backend.app.modules.design.generation.maas.massv2.execute import execute
    from backend.app.modules.design.generation.maas.massv2.grammar import parti_from_record
    reference = SHAPE_FAMILY_REFERENCE_SPAN_M
    try:
        parti = parti_from_record(scheme)
        if parti is None:
            return 'stack-levels-unresolved'
        form = execute(parti, buildable=box(0,0,reference,reference),
                       axis=(1.,0.),height_m=reference)
        if form is None:
            return 'stack-levels-unresolved'
        counts = Counter(item.z_span()[0] for item in form.additive() if item.occupiable)
        return 'stack-levels:'+','.join(str(counts[z]) for z in sorted(counts))
    except (ValueError,TypeError,KeyError,AttributeError,IndexError):
        return 'stack-levels-unresolved'


def _shape_move(evidence):
    if evidence['status'] != 'measured':
        return 'shape-unresolved'
    plans, sections = evidence['plan_components'], evidence['sections']
    # A single convex flat solid is still an extrusion. Merely spelling its
    # constant surfaces or its rectangle does not create another family.
    if plans == [(0, True)] and not sections:
        return None
    plan = '+'.join(f'{holes}{"c" if convex else "n"}' for holes, convex in plans)
    section = '+'.join(f'{top}|{bottom}' for top, bottom in sections) or 'flat'
    return f'shape-plan[{plan}]-section[{section}]'

FAMILY_OF_VERB = {
    # what kind of statement a verb is, at the level a jury reads
    "nest": "relational", "lodge": "relational", "overlap": "relational",
    "interlock": "relational", "merge": "relational", "extract": "relational",
    # `offset` joins them: it used to be a translation and had no family at
    # all, only a place in QUIET. It now delivers a twin held clear of its
    # host, which is the same kind of statement `overlap` makes.
    "offset": "relational",
    "gable": "section", "butterfly": "section", "mansard": "section",
    "vault": "section", "fold": "section", "grade": "section",
    "split": "cut", "carve": "cut", "notch": "cut", "puncture": "cut",
    "inscribe": "cut", "fracture": "cut", "intersect": "cut",
    "cantilever": "banding", "stagger": "banding", "twist": "banding",
    "taper": "banding", "bend": "banding", "pinch": "banding",
    "canopy": "plate",
    "roof": "plate",
    "sink": "ground",
    "lift": "piloti",
    # `embed` is filed with the cuts now, not the relations: it delivers a void
    # in one host rather than a second body related to it. The board curates
    # one seat per family, so a word that changed what it makes has to change
    # which family it is counted in or the curation is counting the old thing.
    "branch": "field", "embed": "cut",
}
OPENERS = ("extrude", "loop", "aggregate", "stack")
# `offset` has left this set. QUIET is for words that change a body without
# changing the composition, and offset now makes a second volume - the BOOK
# reads it as add on multiple, and a verb that delivers a twin is not quiet.
QUIET = {"compress", "expand", "inflate", "shift", "rotate",
         "skew", "align", "realign", "approach"}


def family_key(scheme: dict) -> tuple:
    """(opener, frozenset of move families, stature band) for one sentence."""

    ops = scheme.get("ops") or ()
    opener = "?"
    height = 0.0
    for op in ops:
        word = str(op.get("op") or op.get("verb") or "")
        if word in OPENERS:
            opener = word
            if word == "aggregate" and str(op.get("method") or "") == "stack":
                opener = "aggregate_stack"
            height = max(height, float(op.get("height") or 0.0))
            break
    moves = {
        FAMILY_OF_VERB[str(op.get("op") or op.get("verb") or "")]
        for op in ops
        if str(op.get("op") or op.get("verb") or "") in FAMILY_OF_VERB
    }
    # The open shape contract can change plan or section. Read its actual
    # fields so a shaped body is not filed as an unmodified extrusion.
    shapes = [op for op in ops if str(op.get("op") or op.get("verb") or "") == "shape"]
    shaped_move = _shape_move(shape_family_evidence(scheme)) if shapes else None
    # One dominant move names the family. A marquee added to a plinth-and-
    # turned-tower does not make it a different building - the judges read
    # the strongest statement, so the key does too.
    for dominant in ("relational", "section", "cut", "banding",
                     "piloti", "plate", "field"):
        if dominant in moves:
            moves = {dominant}
            break
    # Except the roof: a jury reads a mansard court ring and a barrel-vaulted
    # ring as different buildings, and one "section" bucket evicted the 3.90
    # mansard for the 4.14 vault. The section family keys on its verb; the
    # eye tier remains the net for genuine lookalikes.
    if moves == {"section"}:
        section_verbs = {
            str(op.get("op") or op.get("verb") or "") for op in ops
            if FAMILY_OF_VERB.get(str(op.get("op") or op.get("verb") or "")) == "section"
        }
        moves = section_verbs or moves
    stature = "low" if height < 0.42 else ("mid" if height < 0.72 else "tall")
    if shaped_move is not None:
        moves = {shaped_move}
    elif opener == 'aggregate_stack' and not moves:
        # Pure assemblies have no separate dominant verb. Their level
        # organization is itself the spatial move: four one-unit levels
        # and two paired levels must not collapse before geometry is judged.
        # Existing dominant relational/section families retain their contract.
        moves = {_stack_level_organization(scheme)}
    return (opener, frozenset(moves), stature)


def family_tag(scheme: dict) -> str:
    """The key as one printable word, for ledgers and selector maps."""

    opener, moves, stature = family_key(scheme)
    return f"{opener}/{'+'.join(sorted(moves)) or '-'}/{stature}"


def one_per_family(entries, *, key_of, score_of):
    """The best entry per family, order preserved by descending score."""

    best: dict = {}
    for item in entries:
        k = key_of(item)
        if k not in best or score_of(item) > score_of(best[k]):
            best[k] = item
    return sorted(best.values(), key=score_of, reverse=True)
