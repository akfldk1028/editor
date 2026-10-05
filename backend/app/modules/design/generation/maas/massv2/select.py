"""Choose the sheet an architect would actually look at.

Eighty-eight masses of which forty were distinct compositions is not a portfolio,
it is a contact sheet with the same building printed four times. Filling a grid
cell is a label; the architect chooses between buildings.

Three rules, in order:

  A mass that is lawful but not occupiable is not an option. That judgement is
  `plausibility`, which uses the project's own floor-viability rule.

  A composition seen twice *in one cell* is one composition, and the signature
  is scale-free so that two drawings of the same idea collapse. It is not
  applied across cells: ground take is one of the grid's two axes, so a scheme
  carried along that axis has moved, not repeated. Deduping globally deleted
  the move before the cells were ever looked at - measured on the Uijeongbu
  parcel, raked_bar stood lawful and occupiable in four different cells at an
  articulation of 0.309 and only one copy survived, which handed
  dispersed|solid_body to a scheme scoring 0.280.

  One per grid cell, and the one kept is the most articulate. Cells are filled
  scarcest-first, and a cell prefers a composition no other cell has taken, so
  an abundant cell cannot spend the only occupant a thin cell had.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from math import atan2, ceil, degrees
from typing import Any, Iterable

from shapely.geometry import Polygon

from backend.app.modules.design.generation.maas.source_geometry.ir import SourceMass

from backend.app.modules.design.generation.maas.massv2.composition import PRIMARY_SHARE
from backend.app.modules.design.generation.maas.massv2.form import MatrixForm
from backend.app.modules.design.generation.maas.massv2.measure import FormMeasurement
from backend.app.modules.design.generation.maas.massv2.plausibility import Plausibility
from backend.app.modules.design.generation.maas.massv2.profiles import unit_plan


@dataclass(frozen=True)
class Candidate:
    form: MatrixForm
    source: SourceMass
    measurement: FormMeasurement
    plausibility: Plausibility
    cell: str
    ground_take: float
    far_utilization: float


def _surface_identity(surface, default):
    """Canonical typed definition, independent of physical placement scale."""
    def canonical(record):
        if record.get('type') == 'polynomial':
            coefficients = {}
            for i, j, value in record['terms']:
                coefficients[i, j] = coefficients.get((i, j), 0.) + value
            coefficients = {power: value for power, value in coefficients.items() if value != 0}
            if set(coefficients) <= {(0, 0)}:
                return {'type': 'constant', 'height': float(coefficients.get((0, 0), 0.))}
            return {'type': 'polynomial', 'terms': [(*power, float(value))
                    for power, value in sorted(coefficients.items())]}
        if record.get('type') == 'constant':
            return {'type': 'constant', 'height': float(record['height'])}
        if record.get('type') == 'affine':
            return {**record, 'surface': canonical(record['surface'])}
        return record
    record = surface.signature() if surface is not None else {'type': 'constant', 'height': default}
    return json.dumps(canonical(record), sort_keys=True, separators=(',', ':'))


def _shape_identity(item):
    # Bounding boxes contain neither holes nor roof/underside fields. Keep
    # authored unit geometry beside the existing scale-free arrangement key.
    # Polygon normalization removes winding/start-vertex differences only;
    # this is conservative dedup, not a proof of arbitrary solid equivalence.
    region = item.plan_region if item.plan_region is not None else Polygon(unit_plan(item.plan))
    return (region.simplify(0, preserve_topology=True).normalize().wkb_hex,
            _surface_identity(item.top_surface, 1.),
            _surface_identity(item.bottom_surface, 0.))


def composition_signature(form: MatrixForm) -> tuple:
    """What this composition is, independent of how big it was drawn.

    Every volume is expressed as a fraction of the whole form's bounding box, so
    a scheme and the same scheme at 45% ground take collapse to one signature.
    Rounding is coarse on purpose: two volumes a few centimetres apart in a
    sixty-metre composition are the same design decision.
    """

    additive = form.additive()
    if not additive:
        return ()
    corners = [corner for item in additive for corner in item.corners()]
    min_x = min(x for x, _y, _z in corners)
    max_x = max(x for x, _y, _z in corners)
    min_y = min(y for _x, y, _z in corners)
    max_y = max(y for _x, y, _z in corners)
    min_z = min(z for _x, _y, z in corners)
    max_z = max(z for _x, _y, z in corners)
    span_x = max(max_x - min_x, 1e-6)
    span_y = max(max_y - min_y, 1e-6)
    span_z = max(max_z - min_z, 1e-6)

    entries = []
    for item in form.placements:
        item_corners = item.corners()
        xs = [x for x, _y, _z in item_corners]
        ys = [y for _x, y, _z in item_corners]
        zs = [z for _x, _y, z in item_corners]
        entries.append((
            item.kind,
            round((min(xs) - min_x) / span_x, 2),
            round((min(ys) - min_y) / span_y, 2),
            round((min(zs) - min_z) / span_z, 2),
            round((max(xs) - min(xs)) / span_x, 2),
            round((max(ys) - min(ys)) / span_y, 2),
            round((max(zs) - min(zs)) / span_z, 2),
            _shape_identity(item),
        ))
    return tuple(sorted(entries))


# How many volumes a winning Korean entry is made of. Measured across 2014-2024
# competition winners by small practices: 3.4 masses, 1.3 external vertical
# circulations, 2.5 three-dimensional exterior spaces, 2 principal cladding
# materials (김경율, 서울대 석사, 2026).
#
# A preference and not a gate. Six volumes is not unlawful, it is simply not
# what wins there, and the number is a distribution rather than a rule - which
# is the mistake `MIN_TIER_CONTRAST` made in the other direction, legislating
# a property that should have emerged. It applies only where the evidence
# does: a brief in hand means this sheet is being judged as a Korean entry.
CORPUS_PIECES = 3.4

# 연면적 ±5% is close to universal across the 설계공모지침서 examined; the same
# documents make exceeding it a deduction and then a disqualification.
BRIEF_TOLERANCE = 0.05

# How many tiles one composition may occupy. See `family_of`: two cells apart is
# the same scheme moved along an axis and is worth showing twice; three is the
# same drawing printed three times.
MAX_TILES_PER_FAMILY = 2


def _brief_tolerance(item) -> float | None:
    """How far off the brief this scheme is, or None if it has no brief."""

    target = item.form.extra.get("programme_target")
    capacity = float(item.form.extra.get("far_capacity_m2") or 0.0)
    if not target or capacity <= 0.0:
        return None
    delivered = item.far_utilization * capacity
    return abs(delivered - float(target)) / float(target)


def piece_count(form: MatrixForm) -> int:
    """Volumes as placed, not as the compiler sliced them.

    The compiler cuts every volume at each storey, so counting bands reports a
    single deformed mass - which is BIG's own signature in seven of ten - at
    six and a half pieces.
    """

    return sum(1 for _item in form.additive())


def _piece_distance(item: Candidate) -> float:
    """How far this scheme sits from the corpus, in whole volumes.

    Rounded, so it separates a three-piece scheme from a seven-piece one and
    stays silent between three and four.
    """

    if item.form.extra.get("programme_target") is None:
        return 0.0
    return round(abs(piece_count(item.form) - CORPUS_PIECES))


def _shape_work(item: Candidate) -> float:
    """How much shaping this scheme did, by whichever means it chose.

    Carving in plan and changing in section are not two things a building owes;
    they are two ways of doing the same one. A courtyard block is carved and
    never steps. A stepped tower steps and is convex in every plan. Listing
    them as separate objectives asks each to be both, and balance then punishes
    whichever it is not - measured on the live parcel, that handed
    full_ground|solid_body to a scheme at 0.05 articulation over `stacked_45`
    at 0.55, purely because the stepped one was flat in plan.

    So they are one objective, taken by the larger. Balance belongs between
    things a scheme genuinely owes at the same time - floor area and form -
    and a maximum belongs between substitutes. Using the same rule for both is
    what went wrong, in each direction: a maximum over everything let a scheme
    win on plan void alone, and a leximin over everything let a scheme win by
    being mediocre evenly.
    """

    return max(item.measurement.convexity_drop, item.measurement.section_change)


def _spoken_force(item: Candidate) -> float:
    """How much of the building each word of its sentence actually redrew.

    Both objectives that used to be here score negatively against the only
    judgement of these sheets that comes from outside the geometry. Three
    subagents compared thirty pairs of the ten Uijeongbu alternatives without
    seeing each other's verdicts, and against that ranking:

        far_utilization   rho -0.26     shape_work    rho -0.23
        articulation      rho -0.31     plan_void     rho -0.48

    The selector was rewarding, one for one, what the critics were marking
    down - `kahn_kimbell` came last on every pairing while leading the field on
    both objectives. 용적률 had already measured rho -0.73 against an earlier
    critique round, so this is the third independent look saying the same thing.

    What does predict is whether the words did any work: mean redraw per word
    scores rho +0.62, and the critics' own language for the schemes that won is
    that the operation is visible - "one operation you name in three seconds",
    "the verb is legible in every edge". A mass whose sentence is invisible is
    the failure they tagged seventeen times.

    It is one objective on purpose, and that is a reversal of the note in
    `_balance_keys`. Simulated over the same ten, the balanced pairs are all
    worse than this alone: with far +0.43, with plan compactness +0.50, with a
    word count +0.62 and no better. The warning that note carries was earned by
    articulation, which is a property of a shape; this is a property of a
    sentence, and the sheet is a sheet of sentences.

    A seed family has no sentence, so it reads 0.0 and cannot win a cell it is
    sharing with an authored one. That is the intended reading rather than a
    fallback: this sheet is for options somebody wrote.

    ⚠️ 2026-09-03: what the runner writes into `spoken_force` is no longer the
    mean this note measured. The mean rewards a sentence whose words are all
    equally loud, which is the opposite of the brief authoring is given ("one
    decisive move per scheme") and of what a jury grades under CONCEPT - and
    the sheets it selected were read by the architect as assemblies of equal
    parts. It is now the loudest word carried by its support, 3:1. The mean
    rides along as `spoken_mean` so the correlation above can be re-measured
    against the new reading rather than argued about.
    """

    return float(item.form.extra.get("spoken_force") or 0.0)


# What a scheme is asked to be good at, once its cell has already said where it
# sits. Neither grid coordinate is here and that is deliberate: ground take and
# plan void are the axes, so scoring them scores the thing every occupant of a
# cell has in common.
def _shape_read(item: Candidate) -> float:
    """Is this shaped at all, asked without asking where its cell is.

    `FormMeasurement.articulation` is the max of three readings and one of them
    is `plan_void_ratio`, which is a grid coordinate - so the whole measure is
    the void axis whenever the void dominates, and `test_no_objective_reads_
    either_grid_coordinate` refuses it, correctly. This takes the other two.

    Chosen by measurement, against a sample drawn evenly across the compiled
    pool rather than the delivered shortlist, judged pairwise in two independent
    rounds under one prompt:

        objective                   round 1   round 2   with the void axis
        plan_void_ratio              +0.538    +0.536   it is the void axis
        far_utilization              -0.566    -0.540      -0.71
        convexity_drop               +0.329    +0.343      +0.87
        articulation (with void)     +0.263    +0.253      +0.29
        max(convexity, section)      +0.237    +0.234      +0.18   <- this
        section_change alone         +0.106    +0.067       0.00

    Everything that reads stronger is a grid coordinate under another name.
    Dropping the void term costs 0.026 of correlation and halves what the
    objective shares with the axis; against ground take it reads -0.10, and
    against `spoken_force` +0.43, so it is neither the grid nor a copy of the
    objective already here.

    ⚠️ On the delivered shortlist the same measure reads +0.028 and +0.020 - no
    relationship at all, which is why it had looked useless. That sample is
    chosen by `spoken_force`, and inside the winners of a contest the criterion
    that decided it stops varying, so every correlation measured there is about
    what the winners had to overcome. Both members of this tuple had the
    opposite sign on it. See `tools/judge_fit.py` and `tools/sample_pool.py`.
    """

    measurement = item.measurement
    return max(measurement.convexity_drop, measurement.section_change)


def _composed(item: Candidate) -> float:
    """Do these parts read as one building - and does one of them lead.

    The first objective in this module that is about composition rather than
    quantity or roughness. `composition.read` measures what Akin and
    Moustapha observed architects doing: a small set of regulating elements
    (alignment lines, shared faces, datums) explaining where every part sits.
    A field of equal boxes on eight lines of their own scores at the floor; a
    body with its wings landing on its own faces scores near the ceiling.

    Two readings, one number, because they are one judgement:

        economy    parts explained per regulating line (1.0 is a pile)
        dominance  the largest body's share of the mass

    Economy is mapped from 1.0 (a line per part) to 3.0 (three parts per
    line) because past three the reading stops improving - a bar with four
    wings on one axis is as composed as a bar with eight. A single-body
    scheme is composed by definition and reads 1.0 rather than being asked
    to prove a relation it does not have.
    """

    reading = item.form.extra.get("composition")
    if not reading:
        # The runner stamps the reading onto the form; anything that builds a
        # candidate without going through it (tests, tools) is read straight
        # off the compiled geometry rather than scored as a default, which
        # would make this objective silently constant.
        from backend.app.modules.design.generation.maas.massv2.composition import read as _read_composition
        reading = _read_composition(item.source).to_dict()
    parts = int(reading.get("parts") or 0)
    if parts <= 1:
        return 1.0
    economy = float(reading.get("economy") or 0.0)
    dominance = float(reading.get("dominance") or 0.0)
    explained = float(reading.get("explained_share") or 0.0)
    held = max(0.0, min(1.0, (economy - 1.0) / 2.0))
    led = max(0.0, min(1.0, dominance / PRIMARY_SHARE))
    return (held * explained + led) / 2.0


OBJECTIVES: tuple[tuple[str, Any], ...] = (
    ("spoken_force", _spoken_force),
    ("composed", _composed),
    ("shape_read", _shape_read),
)

# Neither entry is a grid coordinate, and that is the rule this tuple is kept
# to: ground take and plan void are the axes, so scoring them scores the thing
# every occupant of a cell already has in common.
#
# `far` and `shape_work` used to be here and were removed on measurement - their
# correlation with judged ranking flipped sign between rounds. So did the first
# reading of both members above, on a sample that had been selected by one of
# them. An axis earns its place by holding its sign, and its size, over two
# rounds against an unselected sample. Nothing else.


def _brief_fit(item: Candidate) -> float:
    """How near the delivered floor area is to what the brief asked for.

    Under a brief, 용적률 utilisation stops being an objective - every scheme
    is supposed to arrive at the same number, and the sheet is judged on
    hitting it. A 설계공모지침서 gives 연면적 with a ±5% tolerance and treats
    exceeding it as a deduction and then a disqualification, so nearer is
    simply better and there is no credit for more.
    """

    target = item.form.extra.get("programme_target")
    if not target:
        return item.far_utilization
    delivered = item.far_utilization * _far_capacity(item)
    return 1.0 - min(1.0, abs(delivered - float(target)) / float(target))


def _far_capacity(item: Candidate) -> float:
    """Recover the parcel's capacity from the share the candidate carries."""

    return float(item.form.extra.get("far_capacity_m2") or 0.0)


def _ground_capacity(item: Candidate) -> float:
    """The ground the law allows, which is what `ground_take` is a share of."""

    return float(item.form.extra.get("ground_capacity_m2") or 0.0)


def _ground_released(item: Candidate) -> float:
    """How much of the ground the building gave back.

    The Korean reading of a good mass is the opposite of the one this module
    started with. Its praise vocabulary is about a building imposing less -
    "규모에 비해 가볍고 경쾌", "매스가 덜 느껴져서 좋음", "볼륨을 줄이는 효과",
    "1층의 비워놓기 공간 계획" - and winners include a 청년문화센터 at 7.88%
    건폐율 and a 커뮤니티센터 at 6.94%. Articulation is not what they are
    scoring; how little ground the building takes is closer to it.

    ⚠️ But under a brief it has to become a target, and the first two attempts
    got that wrong in opposite ways.

    Unbounded, it is not an objective about the ground at all. With 연면적 fixed,
    건폐율 is 연면적 over storeys over parcel, so `1 - ground_take` is monotone in
    storey count - "build taller" written in the other direction. The sheet
    showed exactly that: a 1,546 m2 주민센터 on a 275 m2 footprint at 5.8
    storeys, and one pick at 6.8% and 9.1. The two winners cited above are
    buildings whose 연면적 was not pinned to 62% of a 2,500 m2 plot; theirs is a
    low building on a large site, which is the opposite reading.

    Saturating it below a floor did nothing, and measurably: eight of the
    fifteen picks fell under the floor and *tied* there, so the ordering was
    decided by whatever came first and the sheet came back identical. A ceiling
    on the reward is not a preference.

    So it is a distance from a target, which is the shape `_piece_distance`
    already uses against `CORPUS_PIECES` in this module. The target is the
    coverage that delivers this brief in the storeys the brief itself needs -
    `Schedule.storeys_needed` rounded up, never under two, the same number the
    run now hands the sentences as their height budget. On 효돈동 that is 1,546
    over two storeys over a 1,498 m2 allowance: 52% of the ground the law
    allows, 31% of the parcel. A 주민센터 covering a third of its plot in two or
    three storeys, rather than a stick covering a ninth in six.

    Both directions cost: over the target the building is taking ground it does
    not need, under it the building is going up instead of out.
    """

    take = min(1.0, max(0.0, item.ground_take))
    target = item.form.extra.get("programme_target")
    ground = _ground_capacity(item)
    if not target or ground <= 0.0:
        return 1.0 - take
    storeys = max(2.0, ceil(float(target) / ground))
    wanted = min(1.0, float(target) / storeys / ground)
    if wanted <= 1e-9:
        return 1.0 - take
    return max(0.0, 1.0 - abs(take - wanted) / wanted)


# What a scheme is asked to be good at once a brief says how large it is. The
# pair above stops meaning anything there: every scheme targets the same floor
# area, and the mass a Korean jury rewards is the plain one with a good yard,
# which `shape_work` scores down by construction. Measured across the mixed
# corpus, the Korean sentences average 0.317 articulation against 0.407 for the
# international ones and were selected once in ten deliveries despite a 100%
# survival rate - the selector was refusing what the research says wins.
def _storeys_for_the_brief(item: Candidate) -> float:
    """How near the delivered storey count is to the one the brief implies.

    Type, not coverage. `ground_released` used to carry this and could not: 건폐율
    is a grid axis and an objective may not read one, which is this module's own
    rule and now its test. Dropping it was right and cost the reading it was
    standing in for - the fifteen chosen went from a 2.5-storey median to 3.5,
    which on a 1,546 m2 주민센터 is the difference between a building and a stack.

    Storeys are not an axis. Neither grid coordinate is recoverable from this:
    the same storey count occurs at every coverage the brief allows, because
    with 연면적 fixed the two are the same number seen twice - 1,546 over one
    storey is 61.8% and unlawful, over two is 30.9%, over four is 15.5%. What
    the brief actually implies is `Schedule.storeys_needed` rounded up, never
    under two, the same number the run hands each sentence as its height
    budget, and a scheme is scored on how near it lands.

    Both directions cost. Under the target the building is spreading further
    than its programme needs; over it, it is going up instead of out.
    """

    target = item.form.extra.get("programme_target")
    ground = _ground_capacity(item)
    capacity = _far_capacity(item)
    if not target or ground <= 0.0 or capacity <= 0.0:
        return 0.0
    delivered_area = item.far_utilization * capacity
    footprint = max(item.ground_take * ground, 1e-9)
    storeys = delivered_area / footprint
    wanted = max(2.0, ceil(float(target) / ground))
    return max(0.0, 1.0 - abs(storeys - wanted) / wanted)


def _has_a_way_in(item: Candidate) -> float:
    """Whether the mass shows where it is entered from the street.

    The one axis in this module put in by judges rather than by argument. Three
    blind rounds and six judges wrote the same criticism of this corpus - the
    way in is not in the drawing, "주소·마당·현관 같은 대지와의 접점이 캡션으로만
    존재한다" - and when `approach` was built and five sentences using it were
    mixed blind with seven of this selector's own picks, two judges who were
    told nothing about which was which read it straight off the drawings:

        approach 5장   기존선발 7장
        심판 D  3.45      2.79       진입 보임  4/5   0/7
        심판 E  3.37      2.44       진입 보임  5/5   0/7

    Neither saw an entrance in a single one of the seven the selector chose.
    Same sign, same size, two rounds, on a sample the objective did not select -
    which is the bar this module sets, and no other axis here was ever put to
    exactly this test.

    It reads the sentence rather than the geometry, and that is deliberate: an
    approach is a recess at a particular edge for a particular reason, and a
    recess of the same shape cut anywhere else is not one. `postcondition`
    already refuses a word that did not redraw the mass, so a sentence that says
    `approach` and delivers nothing never reaches here.
    """

    # `Parti.evidence` writes `operations`, and each entry names the word under
    # `verb`. Reading `ops`/`op` - which is what the authored JSON uses - gave
    # an empty list and a constant zero, an objective that scores nothing while
    # looking like it scores something.
    ops = ((item.form.extra.get("parti") or {}).get("operations")) or ()
    return 1.0 if any(str(op.get("verb")) == "approach" for op in ops) else 0.0


def _turned_against_each_other(item: Candidate) -> float:
    """How many bearings the composition holds, as a share of its volumes.

    The complaint this answers is "it comes out like Lego", and it is measured
    rather than impressionistic: every one of the fifteen selected masses had
    all of its volumes on a single bearing, while ninety-one sentences stood at
    the coverage the brief wants and seventeen of those turn their volumes
    against one another - `b_moyeo_teulda` on seven bearings, `c_torsion_field`
    on six. The supply is there and the sheet never showed it.

    It never showed it because under a brief there was effectively one axis.
    Every scheme is resized to the same 연면적, so `brief_fit` barely varies,
    and a balance criterion over one objective is arbitrary tie-breaking - among
    schemes at the same coverage the order fell to whatever came first, and
    boxes are more numerous.

    A volume turned about its own centre is a crooked box; volumes turned
    against each other are a composition that faces more than one way. So this
    counts distinct bearings, not rotation: `rotate about:` a shared centre and
    `aggregate turn` both register, and a whole mass spun on the parcel does
    not.

    Saturating at three. Two bearings is a building that has turned to address
    something; three is a field. Past that it is a pile, and the number stops
    saying anything a jury reads.
    """

    bearings = set()
    for placement in item.form.additive():
        matrix = placement.matrix
        bearing = degrees(atan2(matrix[1][0], matrix[0][0])) % 180.0
        # Three degrees is finer than any bearing this language sets.
        bearings.add(round(bearing / 3.0))
    return min(1.0, max(0, len(bearings) - 1) / 2.0)


# The law and the brief are gates; every axis here is a design decision.
#
# `brief_fit` used to be the first of these and it is gone, because `choose`
# already refuses anything outside the 연면적 tolerance the 지침서 states. Among
# the 1,666 masses that survive that gate, `brief_fit` spans 0.9501 to 0.9999 -
# a 5% band by construction - and `_balance_keys` normalises every objective
# across the pool, which stretches that band over the full range. So a scheme
# 0.1% off the brief outranked a better mass 3% off, and both are inside what
# the brief itself calls acceptable. Where a document says ±5% is fine,
# precision within it is not a virtue, and scoring it spends a design axis on
# compliance that was already decided at the door.
BRIEFED_OBJECTIVES: tuple[tuple[str, Any], ...] = (
    # `ground_released` was here and it should never have been: 건폐율 is one of
    # the grid's two axes, and this module's own rule - stated twice above and
    # enforced by `test_no_objective_reads_either_grid_coordinate` - is that an
    # objective may not read a grid coordinate, because scoring the axis scores
    # the thing every occupant of a cell already has in common. The test only
    # ever walked `OBJECTIVES`, so the briefed tuple carried one for as long as
    # it has existed.
    #
    # What it cost is visible on the sheet. The pool reaches 59.9% 건폐율 and a
    # tenth of it stands above 34.5%, and the fifteen chosen stop at 33.6% -
    # scoring distance from a coverage target flattens exactly the axis the
    # cells exist to spread. An alternatives sheet owes a compact scheme next to
    # an open one; that spread is the grid's job, and it was being undone by an
    # objective that graded it.
    ("storeys_for_the_brief", _storeys_for_the_brief),
    ("way_in", _has_a_way_in),
    ("turned", _turned_against_each_other),
    # Same reading as the unbriefed tuple: a brief changes what a building is
    # for, not whether its parts belong to each other.
    ("composed", _composed),
    # Restored. It was dropped from the briefed set by argument - "the mass a
    # Korean jury rewards is the plain one with a good yard, which shape_work
    # scores down by construction" - and the measurement offered alongside it
    # was about `_shape_work`, a different function, not this one. `_shape_read`
    # is the only objective in this module that carries a two-round judged
    # correlation against an unselected sample (+0.237, +0.234), which is the
    # bar this module sets for an axis, and the briefed sheet had nothing that
    # cleared it. A sheet chosen with no eye-scored axis is what produced the
    # boxes.
    ("shape_read", _shape_read),
)


def _balance_keys(pool: list[Candidate]) -> dict[int, tuple[float, ...]]:
    """Score every candidate on how balanced it is, with no weights.

    A single number decided cells until now and it picked the worse building.
    `splayed_fan` topped its cell at an articulation of 0.79 while measuring
    almost nothing in section or in carving, because a maximum only has to be
    large once - and all five schemes rewritten against the critic's notes lost
    to the versions they were meant to replace.

    So: normalise each objective across the pool, then compare candidates by
    their objectives sorted worst-first. A scheme wins by having no weak side,
    not by having one strong one. This is the criterion behind T-DominO (Gaier,
    Stoddart, Villaggi, Bentley, PPSN 2022), which reports that a quarter of
    NSGA-II's solutions clear the lower quartile on all five of its objectives
    against 99% of its own - the same "nothing passes on every count" symptom
    this sheet has had all along. Sorting is monotone in Pareto dominance, so a
    scheme better on every objective still wins outright; balance only decides
    the cases dominance leaves open, which is most of them.
    """

    # A brief changes what the sheet is being judged on, so it changes the axes.
    objectives = (
        BRIEFED_OBJECTIVES
        if pool and pool[0].form.extra.get("programme_target") is not None
        else OBJECTIVES
    )

    spans: list[tuple[float, float]] = []
    for _name, read in objectives:
        values = [float(read(item)) for item in pool]
        low, high = (min(values), max(values)) if values else (0.0, 0.0)
        spans.append((low, high))

    keys: dict[int, tuple[float, ...]] = {}
    for item in pool:
        scaled = []
        for (_name, read), (low, high) in zip(objectives, spans):
            width = high - low
            scaled.append((float(read(item)) - low) / width if width > 1e-9 else 1.0)
        # Worst-first, so comparing two keys compares their weakest sides first.
        keys[id(item)] = tuple(sorted(scaled))
    return keys


def choose(
    candidates: Iterable[Candidate],
    *,
    require_occupiable: bool = True,
    per_cell: int = 1,
    composition_family: dict[str, str] | None = None,
) -> list[Candidate]:
    """Drop what cannot be occupied, then fill each cell with its best occupant.

    `composition_family` maps a sentence name to its family tag (see
    `family.family_tag`): the name quota below cannot see that six
    differently-named plinth-and-turned-tower schemes are one building, and
    on the audited sheet that family took six of thirty-two seats. The tag
    quota is softer than the name quota on purpose - same principle is still
    a different drawing - so a family past its two seats steps aside only
    while some other family can hold the cell, and a cell never goes empty
    over it.

    When tags are supplied, a second pass exposes one eligible representative
    of each otherwise unrepresented nonempty tag to the downstream jury.
    `per_cell` limits the first, grid-diversification pass; this tagged coverage
    pass may add candidates in an already occupied cell. It does not rank a
    jury winner or change the unconfigured API. Existing geometry dedup and
    per-sentence repetition limits still apply, so aliases of the same
    geometry are not guaranteed separate tag representatives.
    """

    pool = [
        candidate
        for candidate in candidates
        if not (require_occupiable and not candidate.plausibility.occupiable)
    ]
    # An explicit programme is binding, even when every supplied scheme misses.
    # Without one, legal capacity is a ceiling, not an invented minimum brief.
    # Physical eligibility still applies above; visual/spatial quality is judged
    # downstream. Low density receives neither an exemption nor a bonus.
    briefed = [item for item in pool if item.form.extra.get('programme_target') is not None]
    if briefed:
        pool = [item for item in briefed
                if (error := _brief_tolerance(item)) is not None and error <= BRIEF_TOLERANCE]
    keys = _balance_keys(pool)

    def rank(item: Candidate) -> tuple:
        return (keys[id(item)], item.far_utilization)

    by_cell: dict[str, dict[tuple, Candidate]] = {}
    for candidate in pool:
        signature = composition_signature(candidate.form)
        cell = by_cell.setdefault(candidate.cell, {})
        held = cell.get(signature)
        if held is None or rank(candidate) > rank(held):
            cell[signature] = candidate

    # Scarcest cell first. A cell with one lawful occupant has no second choice,
    # so it picks before a cell holding a dozen - otherwise the abundant cell
    # takes the composition and the thin one is left empty or with junk.
    order = sorted(by_cell, key=lambda cell: (len(by_cell[cell]), cell))

    taken: set[str] = set()
    times: dict[str, int] = {}
    taken_tags: set[str] = set()
    tag_times: dict[str, int] = {}
    chosen: list[Candidate] = []

    def tag_of(item: Candidate) -> str:
        if not composition_family:
            return ""
        return composition_family.get(family_of(item), "")
    for cell in order:
        # A family that has already had its two outings is out of the running,
        # not merely sorted below. Preferring the unseen is what `taken` does,
        # and it is enough only while some other family is available in the
        # cell - `lab_city` took four of thirteen tiles the moment a change in
        # the geometry made it rank first in cells where nothing else did.
        #
        # Two is the number `family_of` argues for directly: two cells apart is
        # a move along an axis and belongs on the sheet twice, three cells apart
        # is the same drawing printed three times.
        available = [
            item for item in by_cell[cell].values()
            if times.get(family_of(item), 0) < MAX_TILES_PER_FAMILY
        ]
        if composition_family:
            fresh = [
                item for item in available
                if tag_times.get(
                    composition_family.get(family_of(item), ""), 0,
                ) < MAX_TILES_PER_FAMILY
            ]
            if fresh:
                available = fresh
        if not available:
            # The cell goes empty rather than take a third copy. Measured on the
            # 의정부 sheet, four cells had exactly one sentence able to occupy
            # them - the high ground-take column, which only a handful of
            # compositions can reach at all - and `lab_city` printed four times
            # out of thirteen tiles. An empty cell says the supply does not
            # reach here, which is true and useful; a repeated tile says it does,
            # which is neither. This module opens by refusing exactly that trade.
            continue
        ranked = sorted(
            available,
            # An unseen composition first: the sheet is a set of options, and an
            # option the architect has already been shown is worth less than one
            # they have not, even when it measures a little better.
            #
            # Then, where a brief says this is being judged as a Korean entry,
            # the scheme whose volume count is nearer the winners'. Negated so
            # that nearer sorts higher under the reverse below, and rounded so
            # it only speaks when the difference is whole volumes.
            key=lambda item: (
                family_of(item) not in taken,
                bool(tag_of(item)) and tag_of(item) not in taken_tags,
                -_piece_distance(item),
                rank(item),
            ),
            reverse=True,
        )
        seated_here = 0
        families_here: set[str] = set()
        for candidate in ranked:
            if seated_here >= max(1, per_cell):
                break
            family = family_of(candidate)
            # `ranked` was ordered once, before the first seat in this cell
            # was taken, so the second seat could not see the first: five of
            # sixteen sweep01 cells seated the same sentence twice (a siting
            # copy beside its band copy) while a distinct family with a
            # stronger word waited. Two seats in a cell are two buildings -
            # judged against THIS cell's seats; a family seated elsewhere may
            # still take its second outing here (MAX_TILES_PER_FAMILY rules).
            if family in families_here:
                continue
            seated_here += 1
            families_here.add(family)
            taken.add(family)
            times[family] = times.get(family, 0) + 1
            tag = tag_of(candidate)
            if tag:
                taken_tags.add(tag)
                tag_times[tag] = tag_times.get(tag, 0) + 1
            chosen.append(candidate)

    if composition_family:
        # A coarse cell can contain a rotating stack, paired bars, a bridge
        # and a courtyard. Its small quota must not silence three different
        # authored propositions before the visual jury sees any of them.
        # Reuse only physically/programmatically eligible cell representatives;
        # do not resurrect a rejected or duplicate shape from the raw inputs.
        represented_shapes = {composition_signature(item.form) for item in chosen}
        remaining = sorted(
            (item for cell in by_cell.values() for item in cell.values()),
            key=rank, reverse=True,
        )
        for candidate in remaining:
            tag = tag_of(candidate)
            family = family_of(candidate)
            if not tag or tag in taken_tags or times.get(family, 0) >= MAX_TILES_PER_FAMILY:
                continue
            signature = composition_signature(candidate.form)
            if signature in represented_shapes:
                continue
            chosen.append(candidate)
            represented_shapes.add(signature)
            taken.add(family)
            times[family] = times.get(family, 0) + 1
            taken_tags.add(tag)
            tag_times[tag] = tag_times.get(tag, 0) + 1
    return chosen


def family_of(candidate: Candidate) -> str:
    """Which composition this is, before the coverage axis restated it.

    Two cells apart, the same scheme is a move along an axis and belongs on the
    sheet twice - that is what deduping globally got wrong. Three cells apart it
    is the same drawing printed three times, which is what happened the moment
    the ranking changed: `hollow_market_arch` took the arch cell, then took two
    more, and the sixteen tiles read as nine buildings.

    Both suffixes have to be cut, not just the coverage one. A siting copy is
    the same composition standing somewhere else, and keeping `^off_open` in
    the key made it a new family - so `plate_on_four_supports` printed twice on
    one sheet, and `lifted_back_court` twice more.

    The geometry signature cannot police that either, because it is what the
    coverage variants legitimately differ in - growing a scheme wider and growing it
    taller both change its proportions, so its own copies stop matching it. The
    name the variants were derived from does not move, so that is what is
    remembered across cells. Within a cell the signature still rules, since
    there the question really is whether two drawings are one design.
    """

    name = candidate.form.name
    for mark in ("~", "^"):
        name = name.split(mark, 1)[0]
    return name


def summary(chosen: list[Candidate], *, considered: int) -> dict[str, Any]:
    return {
        "schema_version": "arr.maas.massv2_selection.v1",
        "considered": considered,
        "distinct_compositions": len({composition_signature(item.form) for item in chosen}),
        "chosen": len(chosen),
        # Which ones, not just how many. The run recorded the count and the
        # cells and nothing else, so asking "did any sentence using this verb
        # get picked" meant re-running the whole grid. An unauditable choice is
        # the one place this package has no instrument.
        "chosen_names": [item.form.name for item in chosen],
        "cells": sorted({item.cell for item in chosen}),
    }
