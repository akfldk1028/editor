"""Compile placed plans into height-bounded source solids.

Flat placements retain exact band booleans. Legacy roofs and typed top/bottom
surfaces stay separate so each keeps its authored coordinates through clipping.
Explicit unit plans carry arbitrary polygon boundaries and holes. Curves are
sampled, upright height fields; out-of-plane surface transforms and partial-
height cutters through explicit surfaces require interval CSG and are refused.
Legal envelope and floor-area paths remain conservative band/plan proxies.
"""

from __future__ import annotations

from typing import Any

from shapely import affinity
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
from shapely.ops import unary_union

from backend.app.modules.design.generation.maas.source_geometry.ir import SourceMass, SourceVolume
from backend.app.modules.design.generation.maas.source_geometry.solid import AffineSurface, contact_region, inverse_plan_affine, plan_mesh

from dataclasses import replace
from backend.app.modules.design.generation.maas.geometry_language.affine_matrix import compose_matrix4, transform_point3, translation_matrix4, validate_matrix4

from backend.app.modules.design.generation.maas.massv2.form import MatrixForm, Placement
from backend.app.modules.design.generation.maas.massv2.profiles import unit_plan


# Bands thinner than this are a seam between two volumes that end near each
# other, not a layer of the building. The number is the package's own floor on
# how thin anything it builds may be - `_Frame.box` holds every volume to at
# least 0.5 m, and a storey to a storey - so a band under it corresponds to no
# building element at all.
#
# It was 0.05, chosen against float noise, and 5 cm is far below the scale of
# the mistake: measured over the sixteen delivered alternatives, seven of the
# seventy-four prisms drawn were under a metre. In an axonometric each of those
# is a line across a facade that no wall makes, which is what "정갈하지 않다"
# turned out to mean in about a tenth of the cases. The rest of the layering is
# not noise - forty-nine of the seventy-four are 3 m or thicker, and those are
# storeys.
_MINIMUM_BAND_M = 0.5
# Band edges are rounded to four places; every "is this height in this band"
# test must allow at least that much, or a base that rounds the wrong way
# falls out of its own band (the basement and the roof sheet both did).
_EDGE_TOLERANCE_M = 1e-3
# A band whose remaining plan is slighter than this was cut away, not built.
_MINIMUM_BAND_AREA_M2 = 1.0
# Slender structural members (pilotis columns, thin cores) are built and must not be discarded as crumbs.
_MINIMUM_STRUCTURAL_AREA_M2 = 0.05


def _ring_at(placement: Placement, level: float) -> list[tuple[float, float]]:
    """The volume's plan outline at one normalized height, in order."""

    return [
        (x, y)
        for x, y, _z in (
            transform_point3(placement.matrix, (corner[0], corner[1], level))
            for corner in (placement.plan_region.exterior.coords[:-1]
                           if placement.plan_region is not None else unit_plan(placement.plan))
        )
    ]


def _stands_upright(placement: Placement) -> bool:
    """Is this volume's plan the same at every height.

    Cheap and non-recursive, so the plan functions can ask it. Compares the
    posed ring at the bottom and the top point for point, which is exactly what
    a lean or a twist changes.
    """

    bottom, top = _ring_at(placement, 0.0), _ring_at(placement, 1.0)
    return all(
        abs(a[0] - b[0]) < 1e-9 and abs(a[1] - b[1]) < 1e-9
        for a, b in zip(bottom, top)
    )


def _ordered(points) -> Polygon:
    polygon = Polygon(points)
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    return polygon if isinstance(polygon, Polygon) else Polygon()


def _plan(placement: Placement) -> Polygon:
    """Plan outline of a posed volume, over its whole height.

    A volume that stands upright has the same plan at every height, so the
    posed ring in order is exact. A convex hull is not: `concave_l` is one of
    the ten profiles this grammar can name, and its hull is 32% larger than the
    shape - the notch that makes it an L was being filled in, in the measure of
    건축면적, in every downstream metric, and in the drawing. Two sentences in
    the corpus ask for that plan and none of them has ever been drawn with it.

    A leaning or twisting volume is the case the hull was written for: its
    projection over height is the union of every level's ring, and the hull of
    the eight corners is exact for the affine image of a *cube* - which is what
    every leaning volume here is, because the profiles that lean are square.
    """

    if _stands_upright(placement):
        return _upright_plan(placement)
    hull = Polygon([(x, y) for x, y, _z in placement.corners()]).convex_hull
    return hull if isinstance(hull, Polygon) else Polygon()


def _plan_between(placement: Placement, low: float, high: float) -> Polygon:
    """Plan outline of the part of a volume that lies between two heights.

    For an upright box this is the same rectangle at every height, so it agrees
    with `_plan`. For a leaning one it does not, and the difference is the whole
    point: shearing a tower moves its plan sideways as it rises, and taking the
    hull over its full height instead reports one big parallelogram that no
    storey actually has. A leaning tower measured that way came out with a single
    band and zero articulation - the move was in the geometry and invisible to
    every measure downstream.

    The cross-section of an affine cube at a given height is the image of the
    unit square at the corresponding local level, so the two bounding levels are
    enough; anything between them is inside their hull.
    """

    low_z, high_z = placement.z_span()
    span = high_z - low_z
    if span <= 1e-9:
        return _plan(placement)
    if _stands_upright(placement):
        # Same plan at every height, so the slice is the whole plan and the
        # ring in order is exact - hulling it would fill a concave profile in.
        return _upright_plan(placement)
    lower = max(0.0, min(1.0, (low - low_z) / span))
    upper = max(0.0, min(1.0, (high - low_z) / span))
    # The section at the band's own mid-height, not the hull of the two that
    # bound it. A shear translates a box's section without changing its area,
    # so a band's true volume is that area times the band's height - and the
    # hull of the bottom and top sections is strictly larger than either. Read
    # that way `skew` came back adding 140 m3 to a 1,920 m3 body, +7.28%, on an
    # operator whose matrix has |det| = 1: measured against the determinant the
    # placement itself carries, the geometry was right and the reading was not.
    #
    # The midpoint is also what the rest of this function already assumes - the
    # legal envelope four lines down is sampled at `(low + high) / 2.0`, so the
    # band was being cut by the line at its middle while being drawn as the
    # smear of its whole height. For an affine box the mid-section is exact in
    # both area and centroid; for a tapering one it is the midpoint rule, which
    # is far closer than an upper bound.
    middle = _ordered(_ring_at(placement, (lower + upper) / 2.0))
    if not middle.is_empty and middle.area > 0.0:
        return middle
    points = _ring_at(placement, lower) + _ring_at(placement, upper)
    hull = Polygon(points).convex_hull
    return hull if isinstance(hull, Polygon) else Polygon()


def _upright_plan(placement):
    if placement.plan_region is None:
        return _ordered(_ring_at(placement, 0.0))
    m = placement.matrix
    return affinity.affine_transform(placement.plan_region,
                                    (m[0][0],m[0][1],m[1][0],m[1][1],m[0][3],m[1][3]))


def _sheets_settled(form: MatrixForm) -> MatrixForm:
    """A roof sheet sits on the top of the body it covers, whatever moved.

    The plate is placed on its host's crest at authoring size; then the
    coverage band stretches the host, the growth loop grows the rooms and
    leaves structure alone, and the legal fit cuts the body under the
    sunlight envelope - and the sheet stayed where it was authored, 7 m in
    the air over a grown bar. One rule at the one place geometry is decided:
    the host is the occupiable body sharing the most plan with the sheet,
    and the sheet's base is that body's top.
    """

    items = list(form.placements)
    changed = False
    for index, item in enumerate(items):
        if (item.kind != "additive" or item.occupiable
                or getattr(item, "warp", None) is None):
            continue
        plan = _plan(item)
        best, shared = None, 0.0
        for other in items:
            if other is item or other.kind != "additive" or not other.occupiable:
                continue
            area = _plan(other).intersection(plan).area
            # Ties go to the taller body, not to whichever came first in the
            # list: a plate wholly inside both a low wing and a tower shares
            # the same area with each, and list order is not geometry.
            if area > shared or (
                    area > 0.0 and abs(area - shared) < 1e-6
                    and best is not None
                    and other.z_span()[1] > best.z_span()[1]):
                best, shared = other, area
        if best is None:
            continue
        low, high = item.z_span()
        host_low, host_high = best.z_span()
        def material(placement):
            m = placement.matrix
            inverse = inverse_plan_affine((m[0][0],m[0][1],m[1][0],m[1][1],m[0][3],m[1][3]))
            return SourceVolume(placement.role,_plan(placement),0,1,"seat",
                top_drop=placement.top_drop,drop_toward=placement.drop_toward,
                ridge_along=placement.ridge_along,top_profile=placement.top_profile,
                profile_across=placement.profile_across,warp=placement.warp,
                top_surface=AffineSurface(placement.top_surface,inverse) if placement.top_surface is not None else None,
                bottom_surface=AffineSurface(placement.bottom_surface,inverse) if placement.bottom_surface is not None else None)
        plate, host = material(item), material(best)
        shared_plan = plan.intersection(host.footprint)
        mesh = plan_mesh(shared_plan,plan,curved=True,break_lines=host.creases()+plate.creases())
        gaps = [plate.bottom_z(x,y,low,high)-host.top_z(x,y,host_low,host_high)
                for triangle in mesh for x,y in triangle]
        if not gaps:
            continue
        clearance = min(gaps)
        if abs(clearance) > 1e-6:
            items[index] = replace(item, matrix=validate_matrix4(compose_matrix4(
                item.matrix, translation_matrix4((0.0, 0.0, -clearance)))))
            changed = True
    return replace(form, placements=tuple(items)) if changed else form


# What a room needs across a plate, in metres. The same number the
# plausibility gate erodes by when it asks "is this a plate at all"; it lives
# there as MINIMUM_STOREY_WIDTH_M and is repeated as a literal here only
# because plausibility imports this module's output and cannot be imported
# back. Kept in one line so the two are easy to check against each other.
_ROOM_WIDTH_M = 1.5

# How much ground a band may give up to keep its own figure rather than wear
# the parcel's. A clipped plan that keeps this share of its area as a clean
# shrunk figure takes the clean one: the loss is a few per cent of one band's
# footprint, and what it buys is a building that reads as a figure instead of
# as a chamfered lump. Below it the envelope is genuinely shaping the mass and
# the cut is the honest drawing.
_FIGURE_KEEPS_SHARE = 0.88


def _own_figure(plan, clipped, allowed):
    """The plan's own shape, shrunk to fit, when that costs little area.

    Returns the clipped polygon unchanged when shrinking cannot keep enough of
    it - which is what happens where the envelope really bites, and there the
    cut IS the building.
    """

    if plan is None or plan.is_empty or clipped.is_empty:
        return clipped
    # Shrinking a single outline is only an optional Polygon heuristic. A
    # disconnected clip or boundary-only contact must retain its exact result;
    # choosing one component or reconnecting it would change the legal cut.
    if not isinstance(plan, Polygon) or not isinstance(clipped, Polygon):
        return clipped
    if len(clipped.exterior.coords) <= len(plan.exterior.coords):
        return clipped
    if allowed.contains(plan):
        return plan
    centre = plan.centroid
    low, high = 0.5, 1.0
    best = None
    for _step in range(12):
        middle = (low + high) / 2.0
        trial = affinity.scale(plan, xfact=middle, yfact=middle,
                               origin=(centre.x, centre.y))
        if allowed.contains(trial):
            best, low = trial, middle
        else:
            high = middle
    if best is None or best.area < _FIGURE_KEEPS_SHARE * clipped.area:
        return clipped
    return best


def _polygon_parts(geometry):
    """Keep all material polygons, including mixed boundary-contact results."""
    if isinstance(geometry, Polygon):
        yield geometry
    elif isinstance(geometry, (MultiPolygon, GeometryCollection)):
        for part in geometry.geoms:
            yield from _polygon_parts(part)


def _without_clip_waste(form: MatrixForm, low: float, high: float,
                        parts: list[Polygon]) -> list[Polygon]:
    """Drop the offcuts a band leaves beside a real plate.

    The envelope cuts a band and leaves a sliver at one end; the sliver is
    not a body, and the cleanliness gate downstream refuses the whole mass
    for carrying it. Dropped only when a piece of the SAME band still holds
    a room - a band whose every piece is sub-room is the thing itself, and
    the gate should still see it.
    """

    if len(parts) < 2:
        return parts

    def holds_a_room(piece) -> bool:
        try:
            return not piece.buffer(-_ROOM_WIDTH_M, join_style=2).is_empty
        except Exception:  # pragma: no cover - GEOS refusing an erosion
            return True
    # A column is narrow because it is a column. This ran before the
    # structural classification, so a `split` + `lift` sentence - a fat
    # un-lifted half and four legs in one band - lost its legs here: the
    # lifted body then read as ungrounded, the drawing floated it, and the
    # legs' footprint left 건축면적. `_part_is_structure` is the same question
    # the band loop asks a few lines later.
    kept = [piece for piece in parts
            if holds_a_room(piece) or _part_is_structure(form, low, high, piece)]
    return kept if kept else parts


def _band_edges(form: MatrixForm, *, storey_height_m: float | None = None) -> list[float]:
    """Cut heights, taken from the volumes' own tops and bottoms.

    Sampling at a fixed count would put band edges where no volume changes, and
    would miss a setback that happens between two samples.

    A volume that leans is the exception: its plan moves continuously, so its own
    top and bottom are the only edges it declares and the whole tilt collapses
    into one band. Measured that way a tower leaning 35 degrees reported a single
    band and zero articulation. Those are cut at storeys instead, which is the
    interval the building is actually made of.
    """

    additive = form.additive()
    if not additive:
        return []
    edges: set[float] = set()
    for placement in form.placements:
        low, high = placement.z_span()
        edges.add(round(low, 4))
        edges.add(round(high, 4))
        if storey_height_m and storey_height_m > 1e-6 and _leans(placement):
            level = low + storey_height_m
            while level < high - 1e-6:
                edges.add(round(level, 4))
                level += storey_height_m
    ground = min(low for low, _high in (item.z_span() for item in additive))
    roof = max(high for _low, high in (item.z_span() for item in additive))
    # The edges were rounded to four places; the filter must allow for that.
    # A base below the ground rounds AWAY from zero (-7.848698 -> -7.8487),
    # fell under `ground - 1e-9`, and the whole basement band vanished - the
    # sunken plinth's tower compiled as a box standing on grade. Above grade
    # a base is 0.0 exactly and this never showed.
    ordered = sorted(value for value in edges
                     if ground - _EDGE_TOLERANCE_M <= value <= roof + _EDGE_TOLERANCE_M)
    # Edges closer together than a drawable band collapse to one, and the one
    # that survives is the first - which always shortens whatever declared the
    # later edge as its top, and never lengthens anything. The compiled bands
    # ARE the delivered mass, so this is a delivery loss and not a reading of
    # one: the merge fires in 230 of 901 authored sentences, and on the bench a
    # 0.40 m collapse took 43.2 m3 off a body the sentence had built to 6.40.
    #
    # Measured, not fixed. Keeping instead the edge that leaves the least
    # material in the wrong place - weighted by the plan area of the volume
    # declaring it - moved 103 sentences and came out 12,143 m3 DOWN on net,
    # because the material a moved edge costs belongs to the volumes that SPAN
    # that height, not to the one that declared it. The right objective is the
    # true union volume either side of the choice; until that is measured this
    # stays as it is rather than carrying an unjustified rule in the function
    # every legal area in the system is read through.
    merged: list[float] = []
    for value in ordered:
        if not merged or value - merged[-1] >= _MINIMUM_BAND_M:
            merged.append(value)
    if merged:
        merged[0] = ground
    if merged and roof - merged[-1] >= _MINIMUM_BAND_M:
        merged.append(roof)
    elif merged:
        merged[-1] = roof
    return merged


def _spans(placement: Placement, low: float, high: float) -> bool:
    """Does this volume occupy the open interval, rather than just touch it."""

    z_low, z_high = placement.z_span()
    middle = (low + high) / 2.0
    return z_low - 1e-9 <= middle <= z_high + 1e-9


def _band_parts(
    form: MatrixForm, low: float, high: float, allowed_at=None
) -> list[Polygon]:
    """Every plan piece this band occupies, not just the biggest one.

    Two bars with a gap are two pieces at their own storeys, and keeping only
    the larger one would delete half the building - which is exactly what made
    a paired-bar scheme read as 0.05 open instead of a quarter open. The
    existing bridge does the same thing (`source_bridge._polygon_parts`): each
    piece becomes its own volume record and they share the band's fractions,
    because height bands are legal proxies of one component, not separate
    buildings.
    """

    built = [
        _plan_between(item, low, high)
        for item in form.additive()
        if _spans(item, low, high)
    ]
    built = [item for item in built if not item.is_empty and item.area > 0.0]
    if not built:
        return []
    if allowed_at is not None:
        # Piece by piece before the union: a part that the envelope only
        # grazes keeps its own figure, shrunk a little, instead of wearing the
        # parcel's chamfer. Every mass on the board read as an octagonal lump
        # because this cut applied to the whole; the intersection distributes
        # over the union, so cutting the pieces first changes nothing where
        # the figure is not kept.
        allowed_now = allowed_at((low + high) / 2.0)
        if allowed_now is None or allowed_now.is_empty:
            return []
        built = [_own_figure(item, item.intersection(allowed_now), allowed_now)
                 for item in built]
        built = [item for item in built if not item.is_empty and item.area > 0.0]
        if not built:
            return []
    shape = unary_union(built)
    if allowed_at is not None:
        # The legal line cuts the building; it does not shrink it. A volume that
        # runs past the setback is built up to it and stops, which is what an
        # architect draws and what the compiler can represent - a band is an
        # arbitrary polygon here, not a rectangle. Shrinking it instead put the
        # ceiling on ground take at the largest rectangle *inscribed* in the
        # buildable polygon, and on 의정부 4115011300106840001 that polygon is
        # 1922 m2 inside a 3707 m2 bounding box, so the median scheme claimed
        # 0.38 of a 건폐율 it was allowed to fill.
        allowed = allowed_at((low + high) / 2.0)
        if allowed is None or allowed.is_empty:
            return []
        shape = shape.intersection(allowed)
        if shape.is_empty:
            return []
    cutters = [
        _plan_between(item, low, high)
        for item in form.subtractive()
        if _spans(item, low, high)
    ]
    cutters = [item for item in cutters if not item.is_empty and item.area > 0.0]
    if cutters:
        shape = shape.difference(unary_union(cutters))
    if shape.is_empty:
        return []
    has_structural = any(
        (not getattr(item, "occupiable", True) or getattr(item, "plan", "") == "circle" or getattr(item, "role", "") in ("column", "piloti", "support"))
        for item in form.additive()
        if _spans(item, low, high)
    )
    min_area = _MINIMUM_STRUCTURAL_AREA_M2 if has_structural else _MINIMUM_BAND_AREA_M2
    parts = list(_polygon_parts(shape))
    return [
        part
        for part in parts
        if isinstance(part, Polygon) and part.area >= min_area
    ]


def _leans(placement: Placement) -> bool:
    """Does this volume's plan move as it rises."""

    low, high = placement.z_span()
    if high - low <= 1e-9:
        return False
    if _stands_upright(placement):
        return False
    bottom = _ordered(_ring_at(placement, 0.0))
    top = _ordered(_ring_at(placement, 1.0))
    if bottom.is_empty or top.is_empty:
        return False
    union = bottom.union(top)
    if union.is_empty or float(union.area) <= 1e-9:
        return False
    return float(bottom.symmetric_difference(top).area) / float(union.area) > 0.02


def compile_matrix_form(
    form: MatrixForm,
    *,
    verb: str = "matrix_place",
    storey_height_m: float | None = None,
    allowed_at=None,
) -> SourceMass | None:
    """Compile placements into a `SourceMass`, or `None` if nothing survives.

    `allowed_at(height) -> Polygon | None` is the parcel's legal plan at a
    height, already setback- and sunlight-clipped. Given it, every band is cut
    to the shape of the law rather than the law being used to shrink the
    building until it fits inside a rectangle.
    """

    form = _sheets_settled(form)
    edges = _band_edges(form, storey_height_m=storey_height_m)
    if len(edges) < 2:
        return None
    ground = edges[0]
    height = form.height_m()
    if height <= 1e-6:
        return None

    # A tilted volume never merges. `_band_parts` unions every footprint in a
    # band into one polygon, and a union can carry only one roof plane - a
    # gable's two halves came through as a single band with a single tilt, so
    # half of every pitched roof compiled flat. Tilted placements are set
    # aside here and emitted per placement, clipped by the same envelope,
    # with their own tilt carried directly.
    tilted = [
        item for item in form.additive()
        if item.top_surface is not None or item.bottom_surface is not None or (
        float(getattr(item, "top_drop", 0.0) or 0.0) > 0.0
        and (item.drop_toward is not None
             or getattr(item, "ridge_along", None) is not None
             or getattr(item, "top_profile", None) is not None
             or getattr(item, "warp", None) is not None))
    ]
    flat_form = replace(
        form,
        placements=tuple(
            item for item in form.placements if item not in tilted
        ),
    ) if tilted else form

    volumes: list[SourceVolume] = []
    structural: list[int] = []
    dropped_bands = 0
    for low, high in zip(edges, edges[1:]):
        parts = _without_clip_waste(
            form, low, high, _band_parts(flat_form, low, high, allowed_at))
        role = _band_role(form, low, high)
        is_structure = _band_is_structure(form, low, high)
        for part in parts:
            # A band is structure only when nothing occupiable reaches it,
            # which is right for the band's outline and wrong for its parts:
            # Villa dall'Ava's legs stand in the same band as the half that
            # was not lifted, so the band is a floor, the legs were emitted
            # as occupiable volumes, and every small-volume rule (the crumb
            # gate first) read four columns as four shards. A part is
            # structure when everything standing on it is.
            if is_structure or _part_is_structure(form, low, high, part):
                structural.append(len(volumes))
            volumes.append(
                SourceVolume(
                    role=role,
                    footprint=part,
                    bottom_fraction=max(0.0, (low - ground) / height),
                    top_fraction=min(1.0, (high - ground) / height),
                    verb=verb,
                )
            )
        emitted = bool(parts)

        def _tilted_piece(item, lo: float, hi: float, *, drop: float, toward,
                          ridge=None, profile=None, across=None,
                          clip_at: float | None = None, warp=None,
                          top_surface=None, bottom_surface=None) -> bool:
            plan = _plan_between(item, lo, hi)
            authored_domain = plan
            # The profile's authored range, read off the UNCLIPPED plan: a
            # fragment must remember where its stations came from or it draws
            # the whole arc across its own leftover width.
            span = None
            if profile is not None and across is not None and not plan.is_empty:
                ux, uy = across
                stations = [x * ux + y * uy for x, y in plan.exterior.coords]
                span = (min(stations), max(stations))
            if allowed_at is not None:
                # The roof is cut where its BODY is cut, not at its own
                # midpoint: the sunlight envelope shrinks with height, so a
                # roof sampled 3.4 m above the storeys under it survived
                # where no body did - the audit's shells lying loose beside
                # the building. The caller says which height the pair share.
                allowed = allowed_at(clip_at if clip_at is not None
                                     else (lo + hi) / 2.0)
                if allowed is None or allowed.is_empty:
                    return False
                plan = _own_figure(plan, plan.intersection(allowed), allowed)
            cutters = [
                _plan_between(cutter, lo, hi)
                for cutter in form.subtractive()
                if _spans(cutter, lo, hi)
            ]
            cutters = [c for c in cutters if not c.is_empty]
            if cutters:
                plan = plan.difference(unary_union(cutters))
            if plan.is_empty:
                return False
            made = False
            pieces = _polygon_parts(plan)
            for piece in pieces:
                if not isinstance(piece, Polygon) or piece.area < _MINIMUM_BAND_AREA_M2:
                    continue
                if warp is not None:
                    # A warped plate is one surface; a clip fragment of it
                    # is not, so a fragment thinner than a room's depth is a
                    # leftover here too.
                    if piece.buffer(-_MINIMUM_BAND_M / 2.0).is_empty:
                        continue
                elif profile is not None or ridge is not None or drop > 0.0:
                    # A sliver cannot wear a section. Every consumer re-reads
                    # the profile's stations off the fragment's own footprint,
                    # so a 0.2 m ribbon left by the clip carried a whole
                    # sixteen-station arc compressed across itself - the
                    # audit's flame wisps. Morphological opening, the same
                    # erosion the room rule uses: thinner than the package's
                    # own build floor everywhere means it is not a roof, it
                    # is a leftover.
                    if piece.buffer(-_MINIMUM_BAND_M / 2.0).is_empty:
                        continue
                made = True
                # A tilted piece of something that is not a room - a warped
                # roof plate - is structure, the same channel the flat loop
                # gives legs and canopies; without this the plate met the
                # crumb and chimney rules as if it were a room.
                if not item.occupiable:
                    structural.append(len(volumes))
                volumes.append(SourceVolume(
                    role=item.role,
                    footprint=piece,
                    bottom_fraction=max(0.0, (lo - ground) / height),
                    top_fraction=min(1.0, (hi - ground) / height),
                    verb=verb,
                    top_drop=drop,
                    drop_toward=toward,
                    ridge_along=ridge,
                    top_profile=profile,
                    profile_across=across,
                    profile_span=span,
                    top_walkable=bool(getattr(item, "top_walkable", False)),
                    warp=warp,
                    top_surface=top_surface,
                    bottom_surface=bottom_surface,
                    authored_domain=authored_domain if (drop > 0 or top_surface is not None
                                                        or bottom_surface is not None) else None,
                ))
            return made

        for item in tilted:
            if not _spans(item, low, high):
                continue
            if item.top_surface is not None or item.bottom_surface is not None:
                # Preserve the local authored frame and the entire vertical
                # band. Several bands of the same surface would duplicate its
                # material and incorrectly flatten its underside.
                z0, z1 = item.z_span()
                if not low-_EDGE_TOLERANCE_M <= z0 < high-_EDGE_TOLERANCE_M:
                    continue
                if any(min(cutter.z_span()[1],z1) > max(cutter.z_span()[0],z0)+1e-6 and
                       _plan(cutter).intersection(_plan(item)).area > 1e-9 and
                       (cutter.z_span()[0] > z0+1e-6 or cutter.z_span()[1] < z1-1e-6)
                       for cutter in form.subtractive()):
                    raise ValueError("partial-height cutters through explicit surfaces require interval CSG")
                m = item.matrix
                inverse = inverse_plan_affine((m[0][0],m[0][1],m[1][0],m[1][1],m[0][3],m[1][3]))
                emitted |= _tilted_piece(item, z0, z1, drop=0, toward=None,
                    top_surface=AffineSurface(item.top_surface, inverse) if item.top_surface is not None else None,
                    bottom_surface=AffineSurface(item.bottom_surface, inverse) if item.bottom_surface is not None else None)
                continue
            # `top_drop` is declared as a share of the volume's own height
            # (form.py) and the renderer reads a volume's drop as a share of
            # the band it arrived in (`_slope_of`) - so carrying the declared
            # number onto a storey-thick top band drew every roof one storey
            # deep at most: a 0.8 pitch on a nine-metre bar rendered as a
            # 2.4 m bevel, and the fifth frame-of-reference mismatch in this
            # package was a house profile that could not be drawn. The roof
            # zone - the declared drop's own depth - is emitted as a single
            # volume whose drop is its full height, and the storeys under it
            # stay flat bands; the declared metres and the drawn metres are
            # the same number for the first time.
            z0, z1 = item.z_span()
            share = min(max(float(item.top_drop), 0.0), 1.0)
            drop_m = max(share * (z1 - z0), _MINIMUM_BAND_M)
            roof_lo = max(z0, z1 - drop_m)
            body_hi = min(high, roof_lo)
            if body_hi - max(low, z0) > 1e-6:
                emitted |= _tilted_piece(
                    item, max(low, z0), body_hi, drop=0.0, toward=None,
                )
            # Band edges are rounded to four places (`_band_edges`), so a
            # band's `low` can sit up to 5e-5 above the volume's own base and
            # a 1e-6 tolerance read "this roof starts in this band" as false
            # - a sheet whose whole height is roof (top_drop 1.0) was then
            # emitted in no band at all and vanished from every grown copy.
            # The tolerance is the rounding's, not the float's.
            if low - _EDGE_TOLERANCE_M <= roof_lo < high - _EDGE_TOLERANCE_M or (
                roof_lo <= z0 + 1e-9
                and low - _EDGE_TOLERANCE_M <= z0 < high - _EDGE_TOLERANCE_M
            ):
                # A profile's heights are shares of the whole volume; the roof
                # band is only its top slice, so the profile is re-read in the
                # band's own terms - the eaves at 0, the crest at 1. Divided by
                # the band the piece ACTUALLY spans, not by `share`: when
                # `_MINIMUM_BAND_M` wins the max above, the two differ, and a
                # profile normalized against one band and drawn over another
                # was stretched by the ratio.
                profile = getattr(item, "top_profile", None)
                band_share = (z1 - roof_lo) / max(z1 - z0, 1e-9)
                if profile is not None and band_share > 1e-9:
                    profile = tuple(
                        (u, min(1.0, max(0.0, (h - (1.0 - band_share)) / band_share)))
                        for u, h in profile
                    )
                emitted |= _tilted_piece(
                    item, roof_lo, z1, drop=1.0, toward=item.drop_toward,
                    ridge=getattr(item, "ridge_along", None),
                    profile=profile,
                    across=getattr(item, "profile_across", None),
                    warp=getattr(item, "warp", None),
                    # Cut where the shoulders are cut: the roof and the body
                    # under it must survive or vanish together.
                    clip_at=(max(low, z0) + roof_lo) / 2.0
                    if body_hi - max(low, z0) > 1e-6 else None,
                )
        if not emitted:
            dropped_bands += 1
    if not volumes:
        return None
    # A roof with nothing under it is not a roof. The coverage band scales
    # a scheme's height, the daylight envelope then cuts the BODY low while
    # a wide roof plate keeps a piece inside the envelope higher up - and a
    # structural piece that touches no other piece would be drawn floating
    # and counted as ungrounded mass. Dropped here, where the geometry is
    # decided; the variant is judged on what remains.
    if structural and DROP_ORPHAN_STRUCTURE:
        keep: list[int] = []
        for index, item in enumerate(volumes):
            if index not in structural or item.plan_at(max(0.0,-ground),
                    item.bottom_fraction*height,item.top_fraction*height) is not None:
                # Rooms always; and structure standing on the ground is
                # never an orphan - a leg at the rim of the tier it holds
                # up overlaps that tier by less than a square metre and
                # was being dropped as if it floated.
                keep.append(index)
                continue
            # Contact in METRES, not fractions: a leg's top and its tier's
            # base differ by rounding (2 mm on a 22 m mass) and a fraction
            # tolerance of 1e-4 read that as a gap - four legs dropped.
            # Overlap relative to the smaller piece, so a slender column
            # under a wide tier still counts.
            touches = False
            for other in volumes:
                if other is item:
                    continue
                contact = contact_region(item, other,
                    (item.bottom_fraction*height,item.top_fraction*height),
                    (other.bottom_fraction*height,other.top_fraction*height),.05)
                if contact is not None and contact.area > min(1.0,.25*min(item.footprint.area,other.footprint.area)):
                    touches = True
                    break
            if touches:
                keep.append(index)
        if len(keep) != len(volumes):
            remap = {old: new for new, old in enumerate(keep)}
            volumes = [volumes[i] for i in keep]
            structural = [remap[i] for i in structural if i in remap]
    if not volumes:
        # Every band was structure with nothing to hold up (a roof plate
        # whose body the envelope cut away), or the envelope cut every band:
        # the mass does not exist. Refuse it the way an empty form is
        # refused, instead of indexing volumes[0] and taking the run down.
        return None
    grounded = [item for item in volumes if item.bottom_fraction <= 1e-6]
    topmost = [item for item in volumes if item.top_fraction >= 1.0 - 1e-6]
    footprint = unary_union([item.footprint for item in grounded]) if grounded else volumes[0].footprint
    if not isinstance(footprint, Polygon):
        # ⚠️ `SourceMass.footprint` is typed as one Polygon, so a mass standing
        # on several bodies loses all but its largest here. This is ground
        # contact and not 건축면적 either - a lifted wing touches nothing - so
        # nothing that has to agree with the law may read it. 건폐율 comes from
        # `legal_fit.ground_area_m2`, which is what the gate checks.
        footprint = max(footprint.geoms, key=lambda item: item.area)
    upper = unary_union([item.footprint for item in topmost]) if topmost else None
    if upper is not None and not isinstance(upper, Polygon):
        upper = max(upper.geoms, key=lambda item: item.area)

    notes = list(form.notes)
    if dropped_bands:
        notes.append(f"matrix_form_dropped_empty_bands={dropped_bands}")

    return SourceMass(
        name=form.name,
        footprint=footprint,
        upper_footprint=upper,
        lower_floor_fraction=None,
        volumes=tuple(volumes),
        surfaces=(),
        verb_trace=(),
        notes=tuple(notes),
        status="compiled",
        metadata=_metadata(
            form, height_m=height, band_count=len(volumes),
            structural_bands=tuple(structural),
            # The parcel's ground is z = 0; a mass whose lowest base is
            # below it carries how far. Fractions stay measured from the
            # base (every consumer assumes that); the datum says where the
            # ground crosses them.
            datum_m=max(0.0, -ground),
        ),
    )


# A diagnosis switch, not a setting: structure that touches nothing is
# dropped (see the block above); turning this off shows what the rule ate.
DROP_ORPHAN_STRUCTURE = True


def _band_is_structure(form: MatrixForm, low: float, high: float) -> bool:
    """Is everything standing in this band something that holds a room up.

    A band is structure only when nothing occupiable reaches it: four columns
    under a plate make one, the plate above does not, and a band where a column
    passes a floor is a floor. Asked of the volumes rather than of the band's
    outline, because a column and a storey are the same shape in plan and
    differ only in what they are for.
    """

    occupants = [item for item in form.additive() if _spans(item, low, high)]
    return bool(occupants) and not any(item.occupiable for item in occupants)


def _part_is_structure(form: MatrixForm, low: float, high: float, part) -> bool:
    """Is everything standing on this part of the band something that holds a room up."""

    min_overlap = 0.04 if part.area < 1.0 else 0.5
    occupants = [
        item for item in form.additive()
        if _spans(item, low, high) and _plan(item).intersection(part).area >= min_overlap
    ]
    return bool(occupants) and not any(item.occupiable for item in occupants)


def _band_role(form: MatrixForm, low: float, high: float) -> str:
    """Name the band after whichever volume actually dominates it.

    Roles carry the hierarchy the selection quotas read, so a band named after
    the wrong volume is a band that votes for the wrong family.
    """

    occupants = [
        (item, _plan(item).area)
        for item in form.additive()
        if _spans(item, low, high)
    ]
    if not occupants:
        return "matrix_band"
    return max(occupants, key=lambda pair: pair[1])[0].role


def _metadata(
    form: MatrixForm,
    *,
    height_m: float,
    band_count: int,
    structural_bands: tuple[int, ...] = (),
    datum_m: float = 0.0,
) -> dict[str, Any]:
    """The fields `SourceMass.signature()` turns into `source_signature`.

    Leaving these empty is not a cosmetic omission: every diversity quota in
    `design/maas/selection/` reads them, and an unnamed language collapses into
    a single "unknown" family that later balancing culls.
    """

    roles = [item.role for item in form.additive()]
    return {
        "primary_language": form.primary_language,
        "secondary_language": form.secondary_language,
        "formal_principle": form.formal_principle,
        "dominant_gesture": form.dominant_gesture,
        "reference_basis": form.reference_basis,
        "authored_height_m": round(height_m, 3),
        "datum_m": round(float(datum_m), 3),
        "authored_floor_height_m": form.floor_height_m,
        "matrix_form": form.evidence(),
        "massing_genome": {
            "schema_version": "arr.maas.matrix_form_genome.v1",
            "roles": roles,
            "band_count": band_count,
            "additive_count": len(form.additive()),
            "subtractive_count": len(form.subtractive()),
        },
        "geometry_authority": "matrix_form_analysis",
        # Which bands are what holds the building up rather than part of it.
        # Read by the plausibility gate, which must not ask a column to be as
        # wide as a storey.
        "structural_bands": list(structural_bands),
        **dict(form.extra),
    }
