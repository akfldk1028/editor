"""Where on the parcel the building sits.

Ground take says how much of the site a scheme claims and the void band says
what kind of figure it is, and neither says where it stands. `seat_on_site`
answers that once, for every scheme, by putting it on the buildable centroid -
so every mass in the archive is centred, and a low-coverage scheme that could
have sat against the street, or held one corner and left a yard, sits in the
middle of an even margin instead.

That is a real architectural decision being made by default. A building pushed
to the road edge makes a forecourt behind it; the same building pushed back
makes a front garden; held to one side it leaves a yard wide enough to be a
place rather than a gap. Those are different proposals, not different pictures
of one proposal.

The anchors are read off the parcel rather than listed here, so this means the
same thing on any site: the buildable polygon's own centre, and the extremes of
its two principal directions. A square site and a long thin one both give four
positions that an architect would recognise, without a number being chosen.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import hypot

from shapely.geometry import Polygon
from shapely.ops import unary_union

from backend.app.modules.design.generation.maas.geometry_language.affine_matrix import compose_matrix4, translation_matrix4, validate_matrix4

from backend.app.modules.design.generation.maas.massv2.compile import _plan
from backend.app.modules.design.generation.maas.massv2.form import MatrixForm


@dataclass(frozen=True)
class Siting:
    """One position on the parcel, named for what it does."""

    siting_id: str
    label: str
    # How far toward the parcel edge, as a share of the room the scheme has.
    # 0.0 is the centre; 1.0 is as far as it can go while staying inside.
    reach: float
    # Which principal direction, and which end of it.
    axis: int
    sign: float


SITINGS: tuple[Siting, ...] = (
    Siting("centred", "Centred on the parcel", 0.0, 0, 0.0),
    Siting("long_front", "Held to one end of the long axis", 0.85, 0, 1.0),
    Siting("long_back", "Held to the other end of the long axis", 0.85, 0, -1.0),
    Siting("cross_side", "Held to one side of the short axis", 0.85, 1, 1.0),
)

# The two an architect actually argues about, once the parcel's open side is
# known: build to it and put the yard behind, or hold back and let the yard be
# the address. They replace the principal-axis pair whenever the open side can
# be worked out, because "one end of the long axis" is a direction with no
# meaning on the ground and "the side you arrive from" is.
OPEN_SIDE_SITINGS: tuple[Siting, ...] = (
    Siting("centred", "Centred on the parcel", 0.0, 0, 0.0),
    Siting("to_open", "Built up to the open side", 0.85, 0, 1.0),
    Siting("off_open", "Held back from the open side", 0.85, 0, -1.0),
    Siting("cross_open", "Held to one side across the open frontage", 0.85, 1, 1.0),
)


def site_open_side_evidence(site) -> dict:
    """One site-aware owner for authoring, siting and delivered rebuilds.

    Registered road geometry takes precedence over cadastral-neighbour guesses.
    The fallback compares the original parcel with its original shared edges;
    an inset buildable outline is never a frontage observation.
    """
    from backend.app.modules.design.generation.maas.massv2.parcel_policy import registered_road_frontage_evidence
    registered = registered_road_frontage_evidence(site)
    if registered is not None:
        sum_x = sum_y = 0.0
        for start, end in registered['segments_local_m']:
            dx, dy = end[0] - start[0], end[1] - start[1]
            # Unit outward normal times edge length. Orientation is that of
            # the registered ring, independent of the caller's ring winding.
            nx, ny = ((dy, -dx) if registered['reference_ring_is_ccw']
                      else (-dy, dx))
            sum_x += nx
            sum_y += ny
        axis = _unit((sum_x, sum_y))
        return {**registered, 'basis': 'official_plan_road_frontages',
                'source_basis': registered['basis'],
                'direction_world_xy': axis if axis != (0., 0.) else None,
                'method': 'length_weighted_outward_normals',
                'vehicle_access_permission': None,
                'vehicle_access_status': 'not_assessed_by_pedestrian_orientation'}
    parcel = getattr(site, 'site_local_utm', None)
    shared = getattr(site, 'shared_edges', ())
    axis = open_side_direction(parcel, shared) if shared else None
    return {'basis': 'original_parcel_unshared_boundary' if shared else 'unavailable',
            'direction_world_xy': axis if axis != (0., 0.) else None,
            'method': 'cadastral_complement_inference',
            'evidence_grade': 'inferred_not_road_verified',
            'vehicle_access_permission': None,
            'vehicle_access_status': 'not_assessed_by_pedestrian_orientation'}


def site_open_side_direction(site) -> tuple[float, float] | None:
    """The site's documented pedestrian address direction, or explicit fallback."""
    return site_open_side_evidence(site)['direction_world_xy']


def open_side_direction(buildable, shared_edges) -> tuple[float, float] | None:
    """Low-level cadastral complement; callers with a site use the owner above.

    `buildable` is a legacy parameter name: production passes the ORIGINAL
    parcel through site_open_side_direction, never an inset legal plan.

    This is an inference from cadastral adjacency, not a road or entrance
    verification. An adjacent parcel can itself be a road, and an unshared
    edge can face a river or green space. The public1 source audit demonstrates
    both why original coordinates matter and why registered evidence wins.

    The result points from the parcel's area centroid toward the length-weighted
    midpoint of unmatched original boundary edges. It grants no access rights.
    """

    if buildable is None or buildable.is_empty:
        return None
    ring = list(buildable.exterior.coords)
    centre = buildable.centroid
    total = 0.0
    sum_x = sum_y = 0.0
    for start, end in zip(ring, ring[1:]):
        middle = ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)
        length = hypot(end[0] - start[0], end[1] - start[1])
        if length <= 1e-9 or _touches_any(middle, shared_edges):
            continue
        total += length
        sum_x += length * (middle[0] - centre.x)
        sum_y += length * (middle[1] - centre.y)
    if total <= 1e-9:
        return None
    return _unit((sum_x / total, sum_y / total))


# A boundary point is "shared" when a neighbour's shared edge runs through it.
# Half a metre: the two polygons come from the same cadastral layer, so they
# agree to well inside that, and nothing in a parcel is decided at that scale.
_SHARED_TOLERANCE_M = 0.5


def _touches_any(point, shared_edges) -> bool:
    for edge in shared_edges or ():
        for start, end in zip(edge, edge[1:]):
            if _distance_to_segment(point, start, end) <= _SHARED_TOLERANCE_M:
                return True
    return False


def _distance_to_segment(point, start, end) -> float:
    px, py = point
    ax, ay = start
    bx, by = end
    dx, dy = bx - ax, by - ay
    length = dx * dx + dy * dy
    if length <= 1e-12:
        return hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length))
    return hypot(px - (ax + t * dx), py - (ay + t * dy))


def principal_axes(buildable: Polygon) -> tuple[tuple[float, float], tuple[float, float]]:
    """The parcel's own long and short directions.

    Taken from the minimum rotated rectangle, which is the parcel's own idea of
    which way it runs - an axis-aligned bounding box would call a diagonal site
    square and put every "held to one end" copy in the same place as the centred
    one.
    """

    box = buildable.minimum_rotated_rectangle
    ring = list(box.exterior.coords)[:4]
    # Adjacent edges, which are the two directions a rectangle has. Taking three
    # edges and sorting them by length takes the long one twice whenever the
    # ring starts on a short side, and then both axes are the same line:
    # measured on 의정부 and 종로 the pair came back 0.0 degrees apart, so all
    # four sitings slid along one direction and `cross_side` was `long_front`
    # under another name. 강남's ring happened to start the other way and was
    # correct. Same fault as `grammar.seed_rectangle` had, in the other file.
    #
    # This is the fallback: whenever the open side can be worked out,
    # `place_on_site` uses it and its perpendicular instead, which is why the
    # three live parcels never reached this.
    adjacent = [
        (ring[i + 1][0] - ring[i][0], ring[i + 1][1] - ring[i][1])
        for i in range(2)
    ]
    adjacent.sort(key=lambda e: hypot(e[0], e[1]), reverse=True)
    long_edge, short_edge = adjacent[0], adjacent[1]
    return _unit(long_edge), _unit(short_edge)


def _unit(vector: tuple[float, float]) -> tuple[float, float]:
    length = hypot(vector[0], vector[1])
    return (0.0, 0.0) if length <= 1e-9 else (vector[0] / length, vector[1] / length)


def _plan_union(form: MatrixForm) -> Polygon:
    return unary_union([_plan(item) for item in form.additive()])


def _moved(form: MatrixForm, dx: float, dy: float) -> MatrixForm:
    if abs(dx) < 1e-6 and abs(dy) < 1e-6:
        return form
    shift = translation_matrix4((dx, dy, 0.0))
    return replace(
        form,
        placements=tuple(
            replace(item, matrix=validate_matrix4(compose_matrix4(item.matrix, shift)))
            for item in form.placements
        ),
    )


def place_on_site(
    form: MatrixForm,
    buildable: Polygon,
    siting: Siting,
    *,
    open_side: tuple[float, float] | None = None,
) -> MatrixForm | None:
    """Move the scheme to this position, or `None` if it has no room to move.

    The travel is bounded by what the scheme can spend without leaving the
    parcel: the difference between the parcel's extent along the axis and the
    scheme's own. A mass that already fills the site has nowhere to go, and
    returning it unchanged would put a duplicate in the archive rather than an
    alternative.
    """

    plan = _plan_union(form)
    if plan.is_empty or buildable.is_empty:
        return None

    here, there = plan.centroid, buildable.centroid
    centred_dx, centred_dy = float(there.x - here.x), float(there.y - here.y)
    if siting.reach <= 0.0:
        return _moved(form, centred_dx, centred_dy)

    if open_side is not None:
        # Front is the way the parcel opens; cross is square to it.
        axes = (open_side, (-open_side[1], open_side[0]))
    else:
        axes = principal_axes(buildable)
    axis = axes[siting.axis]
    if axis == (0.0, 0.0):
        return None

    room = (_extent(buildable, axis) - _extent(plan, axis)) / 2.0
    if room <= 1e-6:
        return None
    travel = room * siting.reach * siting.sign
    return _moved(
        form, centred_dx + axis[0] * travel, centred_dy + axis[1] * travel
    )


def _extent(shape, direction: tuple[float, float]) -> float:
    values = [
        x * direction[0] + y * direction[1]
        for polygon in _polygons(shape)
        for x, y in polygon.exterior.coords
    ]
    return max(values) - min(values) if values else 0.0


def _polygons(shape) -> list[Polygon]:
    if shape is None or shape.is_empty:
        return []
    if isinstance(shape, Polygon):
        return [shape]
    return [item for item in getattr(shape, "geoms", ()) if isinstance(item, Polygon)]


def spread_across_siting(
    form: MatrixForm,
    *,
    buildable: Polygon,
    open_side: tuple[float, float] | None = None,
    sitings: tuple[Siting, ...] | None = None,
) -> list[MatrixForm]:
    """One copy of this composition per position it can actually take.

    With `open_side` the axes are the parcel's own front and cross directions,
    so the copies are "built up to the street", "held back from it" and "to one
    side of it" rather than three directions named after a bounding box.
    """

    if sitings is None:
        sitings = OPEN_SIDE_SITINGS if open_side is not None else SITINGS

    out: list[MatrixForm] = []
    for siting in sitings:
        moved = place_on_site(form, buildable, siting, open_side=open_side)
        if moved is None:
            continue
        out.append(replace(
            moved,
            name=f"{form.name}^{siting.siting_id}",
            extra={**dict(moved.extra), "siting": siting.siting_id},
        ))
    return out


__all__ = ["SITINGS", "Siting", "place_on_site", "principal_axes", "spread_across_siting",
           "site_open_side_direction", "site_open_side_evidence"]
