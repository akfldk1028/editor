"""Measure a form the way the earlier mistakes proved it has to be measured.

Two measurements were wrong today and both were wrong the same way. Unioning
every triangle of a mesh into an orthographic silhouette hid concave cuts,
because the cut face projects into the pocket it opened. Unioning every volume
regardless of height hid courts, because whatever sits above an opening closes
it again. Five of ten operatives read exactly 0.000 open under the second one.

So nothing here flattens. Convexity is measured per band against that band's own
convex hull, and openness against that band's own tightest rectangle - tightest
rather than axis-aligned, because an axis-aligned box makes a plain rotated
solid read as 0.52 open at 45 degrees, which is orientation, not void.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shapely.errors import GEOSException
from shapely.geometry import Polygon
from shapely.ops import unary_union

from backend.app.modules.design.generation.maas.design_space import delivered_void_band
from backend.app.modules.design.generation.maas.floor_viability import DEFAULT_MINIMUM_CLEAR_DEPTH_M
from backend.app.modules.design.generation.maas.source_geometry.ir import SourceMass


@dataclass(frozen=True)
class FormMeasurement:
    """What a form is, in numbers that survive rotation and concavity."""

    convexity_drop: float
    plan_void_ratio: float
    section_change: float
    void_band_id: str
    band_count: int
    footprint_area_m2: float
    height_m: float
    band_profile: tuple[tuple[float, float], ...]

    def articulation(self) -> float:
        """One number for "is this shaped at all", covering both directions.

        A stepped tower is articulate in section and perfectly convex in every
        plan; a courtyard block is the reverse. Reporting only the plan measure
        called the first one 0.000, which is how a whole family of massing
        would get filed as a plain box.
        """

        return max(self.convexity_drop, self.plan_void_ratio, self.section_change)

    def evidence(self) -> dict[str, Any]:
        return {
            "schema_version": "arr.maas.matrix_form_measurement.v1",
            "convexity_drop": round(self.convexity_drop, 4),
            "plan_void_ratio": round(self.plan_void_ratio, 4),
            "section_change": round(self.section_change, 4),
            "articulation": round(self.articulation(), 4),
            "void_band_id": self.void_band_id,
            "band_count": self.band_count,
            "footprint_area_m2": round(self.footprint_area_m2, 2),
            "height_m": round(self.height_m, 3),
            "band_profile": [
                [round(convexity, 4), round(void, 4)] for convexity, void in self.band_profile
            ],
        }


def _convexity_drop(shape: Polygon) -> float:
    hull = shape.convex_hull
    area = float(hull.area)
    return 0.0 if area <= 1e-9 else max(0.0, 1.0 - float(shape.area) / area)


def _void_ratio(shape: Polygon) -> float:
    """Open ground this plan holds - counting only openings that are rooms.

    A void is a place, and the same rule that decides whether a plate is a floor
    decides whether a gap is a court: it has to hold a room. The project already
    owns that rule at 2.4 m of clear depth, and it is applied here to the void
    for the same reason it is applied to the mass - so that one measure of
    habitable size answers both halves of the same question, rather than the
    solid being held to a standard the void is not.

    Without it the axis pays for fragmentation. A fan of thin leaves has a large
    open area between the leaves and none of it is a room, and it collected the
    grid's highest void reading on the live parcel while a courtyard block sat
    below it. The archetypes the band edges are named after are untouched: a
    court 30% of the side, two bars with a gap, an H, a cross - every opening in
    them is many metres across, so their computed edges still mean what they
    say.
    """

    tightest = shape.minimum_rotated_rectangle
    area = float(tightest.area) if tightest is not None else 0.0
    if area <= 1e-9:
        return 0.0
    gap = tightest.difference(shape)
    if gap.is_empty:
        return 0.0
    radius = DEFAULT_MINIMUM_CLEAR_DEPTH_M / 2.0
    try:
        # Morphological opening: erode the gap by half a room's depth and grow
        # it back. What survives is the part of the opening a room fits into;
        # what disappears was a joint between two pieces, not a place.
        rooms = gap.buffer(-radius, join_style=2).buffer(radius, join_style=2)
    except GEOSException:
        return 0.0
    if rooms.is_empty:
        return 0.0
    return max(0.0, min(1.0, float(rooms.area) / area))


def storeys_in(band_height_m: float, *, floor_height_m: float) -> int:
    """How many floors fit in a vertical band. One rule, used everywhere.

    Nearest whole storey, which is what `round` already means - a band two and a
    half storeys tall builds two, and the hand's-width overlap where one volume
    sits on another builds none. No threshold is written here because there is
    nothing to choose: the storey height comes from the parcel's own zoning, and
    the rounding is arithmetic.

    This exists as one function because it was briefly two. The legal fit
    measured floor area from the placements and the report measured it from the
    compiled bands, the two disagreed on slivers, and two schemes the fit had
    made lawful were reported 1% over the 용적률 ceiling.
    """

    if floor_height_m <= 1e-6 or band_height_m <= 0.0:
        return 0
    return max(0, int(round(band_height_m / floor_height_m)))


def gross_floor_area_m2(source: SourceMass, *, floor_height_m: float) -> float:
    """Conservative floor-area proxy: band plans times declared storey counts.

    A scheme that claims a third of the allowed footprint and a fifth of the
    allowed floor area is not a proposal an architect would put forward, it is
    an under-built site. Measuring 용적률 is what lets that be seen and screened
    rather than silently shipped as diversity.

    Uses the same storey rule as the legal fit - see `storeys_in`. Two different
    floor-area measures is how two lawful schemes came to be reported 1% over
    the 용적률 ceiling: the fit measured one way and the report another.
    """

    height = float(source.metadata.get("authored_height_m") or 0.0)
    # 지하층 is left out of 용적률 (건축법 시행령 제119조: 용적률 산정 시 지하층
    # 면적 제외). A band is a basement when its midpoint lies below the
    # parcel's ground, which the compiler stamps as `datum_m` above the
    # mass's own base.
    datum = float(source.metadata.get("datum_m") or 0.0)
    # Curved/explicit members need not be pre-unioned by the compiler. Union
    # their floor proxies instead of double billing coincident material. A
    # band's storey count is fixed BEFORE overlap partitioning: rounding every
    # resulting sliver would let many small overlap edges erase whole floors.
    # The maximum overlapping floor-equivalent density is conservative for
    # each original band. This deliberately does not infer usable floor area
    # from a roof/underside slice, which would change the established legal rule.
    bands = []
    for volume in source.volumes:
        low,high = volume.bottom_fraction*height,volume.top_fraction*height
        floors = storeys_in(high-low,floor_height_m=floor_height_m)
        if floors and (low+high)/2 >= datum:
            bands.append((low,high,floors/(high-low),volume.projection()))
    edges = sorted({z for low,high,_,_ in bands for z in (low,high)})
    total = 0.0
    for low,high in zip(edges,edges[1:]):
        middle = (low+high)/2
        active = sorted((b for b in bands if b[0] <= middle <= b[1]),key=lambda b:-b[2])
        covered = None
        for _bottom,_top,density,plan in active:
            fresh = plan if covered is None else plan.difference(covered)
            total += fresh.area*density*(high-low)
            covered = plan if covered is None else covered.union(plan)
    return total


def _section_change(grouped: dict[tuple[float, float], list[Polygon]]) -> float:
    """How much the plan changes from one band to the next.

    Plan convexity and plan void are both blind to a setback: every storey of a
    stepped tower is a convex closed rectangle, so a shifted stack measured that
    way reads 0.000 - as articulate as a plain box, which it plainly is not.

    Between consecutive bands, the share of the pair that is not shared says how
    much the building moved. Symmetric difference over union, so it is scale
    free and a pure extrusion reads exactly 0.
    """

    if len(grouped) < 2:
        return 0.0
    ordered = [
        parts[0] if len(parts) == 1 else unary_union(parts)
        for _key, parts in sorted(grouped.items())
    ]
    changes: list[float] = []
    for lower, upper in zip(ordered, ordered[1:]):
        union = lower.union(upper)
        if union.is_empty or float(union.area) <= 1e-9:
            continue
        changes.append(float(lower.symmetric_difference(upper).area) / float(union.area))
    return sum(changes) / len(changes) if changes else 0.0


def measure_form(source: SourceMass, *, height_m: float | None = None) -> FormMeasurement:
    """Thickness-weighted band measurement of a compiled mass.

    Weighting by band thickness stops a hairline band - two volumes meeting at
    almost the same level - from counting as much as a whole storey.
    """

    bands = tuple(source.volumes)
    if not bands:
        return FormMeasurement(0.0, 0.0, 0.0, delivered_void_band(0.0).band_id, 0, 0.0, 0.0, ())

    total_height = float(
        height_m
        if height_m is not None
        else source.metadata.get("authored_height_m") or 0.0
    )

    # One band can arrive as several volume records - two bars with a gap are
    # two pieces of the same storey. Measuring the pieces separately would say
    # a single bar is perfectly convex and perfectly closed, which is true of
    # the bar and false of the building. Regroup by the band's own fractions.
    grouped: dict[tuple[float, float], list[Polygon]] = {}
    for volume in bands:
        if volume.section_kind() != "flat":
            # A tilted band is a continuous section event, and grouped by its
            # flat footprint it measured as none at all: the first sloped roof
            # this language drew compiled to one band, read articulation ~0,
            # and lost its grid cell to its own stepped approximation. Slice
            # the wedge into four virtual bands whose plans shrink as the roof
            # descends - the same cut the silence gate uses - so the measures
            # see the slope the drawing shows.
            from backend.app.modules.design.generation.maas.massv2.postcondition import _sliced_by_tilt
            b0, t0 = float(volume.bottom_fraction), float(volume.top_fraction)
            height = float(source.metadata.get("authored_height_m") or 1.0)
            if volume.section_kind() in ("warp", "surface"):
                vertices = [p for triangle in volume.surface_mesh for p in triangle]
                if not vertices:
                    continue
                b0, t0 = (b0+(t0-b0)*min(p[2] for p in vertices),
                          b0+(t0-b0)*max(p[3] for p in vertices))
            for step in range(4):
                lo = b0 + (t0 - b0) * step / 4.0
                hi = b0 + (t0 - b0) * (step + 1) / 4.0
                z = hi * height - 1e-6
                piece = _sliced_by_tilt(volume, z, height)
                if piece is None or piece.is_empty:
                    continue
                key = (round(lo, 4), round(hi, 4))
                grouped.setdefault(key, []).append(piece)
            continue
        key = (round(float(volume.bottom_fraction), 4), round(float(volume.top_fraction), 4))
        grouped.setdefault(key, []).append(volume.footprint)

    weighted_convexity = 0.0
    weighted_void = 0.0
    weight_total = 0.0
    profile: list[tuple[float, float]] = []
    for (bottom, top), parts in sorted(grouped.items()):
        shape = parts[0] if len(parts) == 1 else unary_union(parts)
        thickness = max(0.0, top - bottom)
        convexity = _convexity_drop(shape)
        void = _void_ratio(shape)
        profile.append((convexity, void))
        if thickness <= 1e-9:
            continue
        weighted_convexity += thickness * convexity
        weighted_void += thickness * void
        weight_total += thickness

    if weight_total <= 1e-9:
        convexity_drop = 0.0
        plan_void = 0.0
    else:
        convexity_drop = weighted_convexity / weight_total
        plan_void = weighted_void / weight_total

    return FormMeasurement(
        convexity_drop=convexity_drop,
        plan_void_ratio=plan_void,
        section_change=_section_change(grouped),
        void_band_id=delivered_void_band(plan_void).band_id,
        band_count=len(bands),
        footprint_area_m2=float(source.footprint.area),
        height_m=total_height,
        band_profile=tuple(profile),
    )
