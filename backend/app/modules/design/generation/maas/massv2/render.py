"""Draw a compiled mass so a person can judge it.

Mesh-authoritative BOOK sources draw their complete SourceSurface triangles
with depth testing. Their band proxies are never a visual replacement.
Ordinary authored sources retain the IR surface/prism renderer, including
courtyards and sunken ground. Both paths use the same orthographic camera.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from PIL import Image, ImageDraw, ImageFont

from backend.app.modules.design.generation.maas.source_geometry.ir import MAX_CREASED_PROFILE_POINTS, SourceMass, profile_height
from backend.app.modules.design.generation.maas.massv2.render_mesh import is_mesh_authoritative, physical_triangles, actual_xy_projection, paint_mesh


_YAW = math.radians(-35.0)
_PITCH = math.radians(28.0)


@dataclass(frozen=True)
class _Palette:
    """What the drawing is made of. Two of these, because the drawing is an
    argument about the mass and the palette decides which argument.

    The clay palette reads as a diagram: warm solids on a green parcel, the
    kind of thing that says "this is a study, do not mistake it for a
    building". The massing palette is the white study model the discipline
    actually judges shape by - practice pins its models white precisely so
    nothing but silhouette and proportion can be argued about, and the same
    geometry rendered white was measured to read as a different quality of
    proposal in this project's own review rounds.
    """

    background: tuple[int, int, int]
    site: tuple[int, int, int]
    wall: tuple[int, int, int]
    roof: tuple[int, int, int]
    edge: tuple[int, int, int]
    # A court is a hole in the roof, painted back to the ground it opens onto.
    court: tuple[int, int, int]
    # The boundary a neighbour is already built against. The parcel's open side
    # is whatever is left of the outline, and it is the reason the siting axis
    # points where it does - so the drawing should say which is which.
    party_wall: tuple[int, int, int]
    ink: tuple[int, int, int]
    muted: tuple[int, int, int]
    accent: tuple[int, int, int]


_CLAY = _Palette(
    background=(250, 250, 248), site=(196, 214, 200),
    wall=(214, 132, 66), roof=(238, 168, 92), edge=(120, 68, 26),
    court=(206, 218, 208), party_wall=(128, 122, 116),
    ink=(40, 40, 44), muted=(108, 110, 104), accent=(170, 82, 20),
)
# White model: the faces carry almost no colour, so the edge does the drawing
# and the eye reads silhouette, proportion and the fall of the top surface -
# which is what a massing study is for.
_MASSING = _Palette(
    background=(255, 255, 255), site=(233, 235, 231),
    wall=(235, 235, 231), roof=(253, 253, 251), edge=(58, 58, 62),
    court=(233, 235, 231), party_wall=(150, 150, 146),
    ink=(30, 30, 34), muted=(112, 112, 108), accent=(90, 90, 96),
)
_STYLES = {"clay": _CLAY, "massing": _MASSING}

# One owner, in the IR beside the `top_profile` contract it is a term of.
_CREASE_LIMIT = MAX_CREASED_PROFILE_POINTS

# The active palette. Swapped for the duration of one render call rather than
# threaded through fifteen signatures; the drawing functions are pure readers.
_PAL = _CLAY

_FONT_FACES = ("C:/Windows/Fonts/malgun.ttf", "C:/Windows/Fonts/gulim.ttc")


def _font(size: int, bold: bool = False):
    """A face that can set Hangul. The authors' reasons are written in Korean."""

    faces = ("C:/Windows/Fonts/malgunbd.ttf",) + _FONT_FACES if bold else _FONT_FACES
    for path in faces:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap(text: str, font, width: float) -> list[str]:
    """Break to fit. Korean wraps per character; the space-split alone leaves
    long unbroken runs that overflow the caption block."""

    lines: list[str] = []
    line = ""
    for char in text:
        if char == "\n":
            lines.append(line)
            line = ""
            continue
        trial = line + char
        if font.getlength(trial) > width and line:
            lines.append(line)
            line = char.lstrip()
        else:
            line = trial
    if line:
        lines.append(line)
    return lines


def _elide(text: str, font, width: float) -> str:
    """Cut to the space there is, not to a character count. A fixed `[:44]`
    fits a sheet tile and truncates nothing on a drawing three times as wide,
    which is where the name matters most."""

    if font.getlength(text) <= width:
        return text
    while text and font.getlength(text + "…") > width:
        text = text[:-1]
    return text + "…"


def _project(x: float, y: float, z: float) -> tuple[float, float]:
    sx = x * math.cos(_YAW) - y * math.sin(_YAW)
    sy = x * math.sin(_YAW) + y * math.cos(_YAW)
    return sx, sy * math.sin(_PITCH) - z * math.cos(_PITCH)


class _Slope(tuple):
    """The renderer's reading of a tilted band.

    A tuple, as every drawing helper indexes it, that also remembers the
    volume and the band it came from - so the per-point heights are asked
    of the IR (`SourceVolume.top_z` / `bottom_z`), the one owner of the
    section, instead of being re-derived here per shape.
    """

    volume: Any
    low: float
    high: float

    def __new__(cls, fields, volume, low, high):
        obj = super().__new__(cls, fields)
        obj.volume, obj.low, obj.high = volume, low, high
        return obj


def _bottom_at(x: float, y: float, low: float, slope) -> float:
    """The underside's height at a plan point - flat except for a warped plate."""

    if slope is None:
        return low
    return slope.volume.bottom_z(x, y, slope.low, slope.high)


def _top_at(x: float, y: float, high: float, slope) -> float:
    """The top face's height at a plan point - flat unless the band tilts."""

    if slope is None:
        return high
    return slope.volume.top_z(x, y, slope.low, slope.high)


def _densified(ring, per_edge: int):
    """The ring with `per_edge` points added along every edge."""

    out = []
    count = len(ring)
    for index in range(count):
        (x0, y0), (x1, y1) = ring[index], ring[(index + 1) % count]
        for k in range(per_edge):
            t = k / per_edge
            out.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
    return out


def _break_lines(slope):
    """The plan lines where the top face folds: (px, py, offset) per fold.

    For a ridge that is the one ridge line; for a profile, every interior
    breakpoint station. A vertex is needed on each so the end wall carries
    its peak (or its valley) - without one, the pentagon renders as a
    trapezoid, which was the second life of the half-wedge bug.
    """

    if slope is None:
        return []
    return slope.volume.creases()


def _ridge_points(ring, slope):
    """The ring with a vertex wherever a fold line crosses an edge."""

    out = list(ring)
    for px, py, centre in _break_lines(slope):
        ring_in, out = out, []
        n = len(ring_in)
        for i in range(n):
            x0, y0 = ring_in[i]
            x1, y1 = ring_in[(i + 1) % n]
            out.append((x0, y0))
            v0 = x0 * px + y0 * py - centre
            v1 = x1 * px + y1 * py - centre
            if (v0 < -1e-9 and v1 > 1e-9) or (v1 < -1e-9 and v0 > 1e-9):
                t = v0 / (v0 - v1)
                out.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
    return out


def _clip_halfplane(ring, px, py, centre, side):
    """Sutherland-Hodgman clip of a ring against one side of the ridge line."""

    out = []
    n = len(ring)
    for i in range(n):
        x0, y0 = ring[i]
        x1, y1 = ring[(i + 1) % n]
        v0 = (x0 * px + y0 * py - centre) * side
        v1 = (x1 * px + y1 * py - centre) * side
        if v0 >= -1e-9:
            out.append((x0, y0))
        if (v0 < -1e-9) != (v1 < -1e-9):
            t = v0 / (v0 - v1)
            out.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
    return out if len(out) >= 3 else None


def _depth(x: float, y: float) -> float:
    """How near a plan point sits to the viewer, on the projection's own axis.

    The projected screen-y is sy*sin(PITCH) - z*cos(PITCH) with
    sy = x*sin(YAW) + y*cos(YAW), so at equal height a larger sy draws lower
    on the tile - in front. Painting in ascending sy is the painter's
    algorithm for this camera.
    """

    return x * math.sin(_YAW) + y * math.cos(_YAW)


# A vertex turning less than this reads as a curve continuing, not a corner:
# an oval's 16 facets each turn ~22 degrees and drawing all sixteen verticals
# dressed the first cylinder tower in scaffolding. A chamfer's 45 and a box's
# 90 stay corners.
_SMOOTH_TURN_COS = math.cos(math.radians(30.0))


def _walls(ring: Sequence[tuple[float, float]], low: float, high: float, slope=None):
    # Sorted far-to-near rather than emitted in ring order: ring order painted
    # a rotated body's rear wall over its front wall, and every rotated family
    # - the clasped arms, the turning petals, the winding stack - rendered as
    # a see-through frame the judges rightly refused to believe would stand.
    count = len(ring)
    segments = list(zip(ring, list(ring[1:]) + [ring[0]]))

    def _facing(index: int) -> float:
        (x0, y0), (x1, y1) = segments[index % count]
        # outward-or-inward normal is consistent along the ring, so only the
        # SIGN CHANGE matters for the silhouette test below
        # `_YAW` is already in radians (line 29); converting it again
        # evaluated the silhouette at -0.6 degrees instead of -35, and the
        # verticals on every curved plan sat a third of a turn from where
        # the projection put the outline.
        return (y1 - y0) * math.sin(_YAW) - (x1 - x0) * math.cos(_YAW)

    def _edge_drawn(index: int) -> bool:
        # The vertical edge at vertex `index`, between walls index-1 and
        # index: drawn when the plan genuinely turns there, or when the
        # surface rolls past the view direction - the curve's own silhouette.
        (ax0, ay0), (ax1, ay1) = segments[(index - 1) % count]
        (bx0, by0), (bx1, by1) = segments[index % count]
        ax, ay = ax1 - ax0, ay1 - ay0
        bx, by = bx1 - bx0, by1 - by0
        norm = (math.hypot(ax, ay) or 1.0) * (math.hypot(bx, by) or 1.0)
        if (ax * bx + ay * by) / norm < _SMOOTH_TURN_COS:
            return True
        return _facing(index - 1) * _facing(index) <= 0.0

    quads = []
    for index, ((x0, y0), (x1, y1)) in enumerate(segments):
        quads.append((_depth((x0 + x1) / 2.0, (y0 + y1) / 2.0), index, [
            _project(x0, y0, _bottom_at(x0, y0, low, slope)),
            _project(x1, y1, _bottom_at(x1, y1, low, slope)),
            _project(x1, y1, _top_at(x1, y1, high, slope)),
            _project(x0, y0, _top_at(x0, y0, high, slope)),
        ]))
    for _d, index, quad in sorted(quads, key=lambda item: item[0]):
        smooth = not (_edge_drawn(index) and _edge_drawn(index + 1))
        yield quad, _PAL.wall, not smooth
        if smooth:
            # The fill runs seamless; the edges that ARE there come back as
            # lines - the base always (the body's ground line), a vertical
            # only where the plan turns or the curve rolls past the eye.
            yield [quad[0], quad[1]], None, True
            if _edge_drawn(index):
                yield [quad[0], quad[3]], None, True
            if _edge_drawn(index + 1):
                yield [quad[1], quad[2]], None, True


def _slope_of(volume, low: float, high: float):
    """The renderer's reading of a tilted band: metres of drop and its axis.

    The projection range comes from the volume's own footprint, so the top
    meets `high` at the rear edge and `high - drop` at the front edge exactly.
    """

    if volume.section_kind() == "surface":
        return _Slope(("S",), volume, low, high)
    drop = float(getattr(volume, "top_drop", 0.0) or 0.0)
    if drop <= 0.0:
        return None
    fields = _slope_fields(volume, low, high, drop)
    return _Slope(fields, volume, low, high) if fields is not None else None


def _slope_fields(volume, low: float, high: float, drop: float):
    """The tag tuple the drawing helpers index (kind, band, axes, extents)."""

    warp = getattr(volume, "warp", None)
    if warp is not None:
        (ux, uy), (vx, vy), corners, plate = warp[:4]
        sag = float(warp[4]) if len(warp) > 4 else 0.0
        nu = math.hypot(ux, uy) or 1.0
        nv = math.hypot(vx, vy) or 1.0
        ux, uy, vx, vy = ux / nu, uy / nu, vx / nv, vy / nv
        ulo, uhi = volume._extent_along(ux, uy)
        vlo, vhi = volume._extent_along(vx, vy)
        return ("W", high - low, ux, uy, vx, vy, ulo, uhi, vlo, vhi,
                tuple(float(c) for c in corners), bool(plate), sag)
    points = getattr(volume, "top_profile", None)
    across = getattr(volume, "profile_across", None)
    if points is not None and across is not None:
        ux, uy = across
        norm = math.hypot(ux, uy) or 1.0
        ux, uy = ux / norm, uy / norm
        # The authored span when the volume remembers it: a clip fragment
        # re-deriving the range from its own footprint wore the whole arc
        # compressed across its leftover width.
        span = getattr(volume, "profile_span", None)
        if span is not None:
            return ("P", high - low, ux, uy, span[0], span[1], tuple(points))
        values = [x * ux + y * uy for x, y in volume.footprint.exterior.coords]
        return ("P", high - low, ux, uy, min(values), max(values), tuple(points))
    ridge = getattr(volume, "ridge_along", None)
    if ridge is not None:
        rx, ry = ridge
        norm = math.hypot(rx, ry) or 1.0
        px, py = -ry / norm, rx / norm
        lo_p, hi_p = volume._extent_along(px, py)
        return ("R", drop * (high - low), px, py,
                (lo_p + hi_p) / 2.0, (hi_p - lo_p) / 2.0)
    if volume.drop_toward is None:
        return None
    ux, uy = volume.drop_toward
    lo_p, hi_p = volume._extent_along(ux, uy)
    return (drop * (high - low), ux, uy, lo_p, hi_p)


def _aperture_walls(court, aperture_points, low, high, slope):
    """Only the parts of real inner walls visible through the roof opening.

    Clip both fills and their authored edges in screen space. This does not
    create a floor or change source geometry; the opening hides the walls
    behind the front roof/facade just as an opaque courtyard ring does.
    """
    from shapely.geometry import LineString, Polygon

    aperture = Polygon(aperture_points)
    if not aperture.is_valid:
        aperture = aperture.buffer(0)

    def parts(geometry):
        if geometry.is_empty:
            return
        if hasattr(geometry, 'geoms'):
            for part in geometry.geoms:
                yield from parts(part)
        else:
            yield geometry

    for points, color, seam in _walls(court, low, high, slope):
        face = Polygon(points) if len(points) >= 3 else LineString(points)
        if color is not None:
            for part in parts(face.intersection(aperture)):
                if part.geom_type == 'Polygon':
                    yield list(part.exterior.coords[:-1]), color, False
        if seam:
            edges = face.boundary if face.geom_type == 'Polygon' else face
            for part in parts(edges.intersection(aperture)):
                if part.geom_type in ('LineString', 'LinearRing'):
                    coords = list(part.coords)
                    for first, second in zip(coords, coords[1:]):
                        yield [first, second], None, True


def _faces(polygon, low: float, high: float, slope=None, *, pit_walls: bool = False):
    """Walls for every ring, then the roof drawn as a ring with its holes.

    Drawing only the exterior ring made every courtyard scheme render as a solid
    block - the court was in the geometry and in the measurement, and missing
    only from the picture, which is the worst place for it to be missing. A
    court has walls too, and they face inward.
    """

    outer = [(float(x), float(y)) for x, y in polygon.exterior.coords[:-1]]
    # A walkable slope is ground, and is painted as ground: the site tone
    # climbing the building, which is how the eye reads a roof-landscape.
    walkable = bool(getattr(getattr(slope, "volume", None), "top_walkable", False))
    top_tone = _PAL.site if walkable else _PAL.roof
    if len(outer) < 3:
        return
    folds = _break_lines(slope)
    if folds:
        # A vertex on every fold, or the end face loses its peak.
        outer = _ridge_points(outer, slope)
    if slope is not None and slope[0] in ("W", "S"):
        # A warped surface's edges are straight only along its own axes; a
        # long edge is drawn as a polyline so the sweep of the eave shows.
        outer = _densified(outer, 6)
        # An elevated plate can expose its underside; use the material mesh.
        for triangle in slope.volume.surface_mesh:
            yield ([_project(x,y,low+(high-low)*bottom) for x,y,bottom,_top in triangle],
                   _PAL.wall, False)
    yield from _walls(outer, low, high, slope)
    # Draw the roof first. Each opening's background and aperture-clipped inner
    # walls follow it, so the solid roof cannot erase their visible depth.
    if slope is not None and slope[0] in ("W", "S"):
        # Shared triangulation retains holes and the same sampled heights used
        # by occupied sections and material volume.
        for triangle in slope.volume.surface_mesh:
            yield ([_project(x,y,low+(high-low)*top) for x,y,_bottom,top in triangle],
                   top_tone, False)
        yield ([_project(x, y, _top_at(x, y, high, slope)) for x, y in outer], None, True)
    elif folds and slope[0] == "R":
        # Two planes, drawn as two polygons so the ridge is a drawn line.
        _tag, _drop, px, py, centre, _half = slope
        for side in (1.0, -1.0):
            part = _clip_halfplane(outer, px, py, centre, side)
            if part:
                yield [_project(x, y, _top_at(x, y, high, slope)) for x, y in part], top_tone, True
    elif folds:
        # One plane per profile segment: the ring clipped to the slab between
        # neighbouring fold lines, so every crease is a drawn line - unless the
        # profile is a sampled curve, where the "creases" are an artefact of
        # sampling and drawing them turns a barrel vault into corrugation.
        _tag, _band, ux, uy, lo_p, hi_p, points = slope
        span = hi_p - lo_p
        stations = [lo_p - 1.0] + [c for _px, _py, c in folds] + [hi_p + 1.0]
        creased = len(points) <= _CREASE_LIMIT
        for lo_c, hi_c in zip(stations, stations[1:]):
            part = _clip_halfplane(outer, ux, uy, lo_c, 1.0)
            part = _clip_halfplane(part, ux, uy, hi_c, -1.0) if part else None
            if part:
                yield ([_project(x, y, _top_at(x, y, high, slope)) for x, y in part],
                       top_tone, creased)
        if not creased:
            # A sampled curve's segments are painted seamless (outline in the
            # fill colour), and the roof colour sits two values off the page's
            # white - so the vault had no silhouette at all and the judges read
            # "an amorphous pancake". One unfilled ring drawn over the top puts
            # the curve's edge back without re-corrugating the surface.
            yield ([_project(x, y, _top_at(x, y, high, slope)) for x, y in outer],
                   None, True)
    else:
        yield [_project(x, y, _top_at(x, y, high, slope)) for x, y in outer], top_tone, True
    for interior in polygon.interiors:
        court = [(float(x), float(y)) for x, y in interior.coords[:-1]]
        if len(court) >= 3:
            if not pit_walls:
                if folds:
                    court = _ridge_points(court, slope)
                if slope is not None and slope[0] in ('W', 'S'):
                    court = _densified(court, 6)
            aperture = [_project(x, y, _top_at(x, y, high, slope)) for x, y in court]
            yield aperture, _PAL.court, True
            if pit_walls:
                # A pit in the earth: its walls are drawn AFTER the ground
                # face so the far walls show inside the hole and the court
                # reads as sunken, not as a flat mark on the ground.
                yield from _walls(court, low, high, slope)
            else:
                # Draw after the opening's background; drawing these before
                # the solid roof erased their depth and leaked onto facades.
                yield from _aperture_walls(court, aperture, low, high, slope)
                yield aperture, None, True


def render_masses(
    items: Iterable[tuple[str, SourceMass, dict[str, Any]]],
    output: Path,
    *,
    site_ring: Sequence[tuple[float, float]] | None = None,
    columns: int = 4,
    tile: tuple[int, int] = (330, 300),
    style: str = "clay",
    yaw_degrees: float | None = None,
    pitch_degrees: float | None = None,
) -> Path:
    """Contact sheet, one compiled mass per tile, captioned with its numbers.

    `yaw_degrees` and `pitch_degrees` turn the camera for this call only. Lower
    views can expose real undercrofts hidden by the default roof-first view.
    One fixed viewpoint
    was a single point of failure for the judges - a move aimed away from the
    default yaw could hide entirely - so a judging round renders each mass
    twice, the second time from the other side.
    """

    global _YAW, _PITCH
    if yaw_degrees is not None or pitch_degrees is not None:
        if any(value is not None and not math.isfinite(value)
               for value in (yaw_degrees, pitch_degrees)):
            raise ValueError("camera angles must be finite")
        prior = _YAW, _PITCH
        if yaw_degrees is not None:
            _YAW = math.radians(yaw_degrees)
        if pitch_degrees is not None:
            _PITCH = math.radians(pitch_degrees)
        try:
            return render_masses(
                items, output, site_ring=site_ring, columns=columns,
                tile=tile, style=style,
            )
        finally:
            _YAW, _PITCH = prior

    entries = list(items)
    if not entries:
        raise ValueError("nothing to render")
    # A grid that fills. Six masses in four columns leaves a row of two beside
    # two tiles of blank paper, which is the first thing the eye reads on the
    # sheet and it says the drawing ran out rather than that six were chosen.
    # The widest divisor no larger than the column count squares it off - six
    # into 3x2, eight into 4x2 - and a count with no divisor keeps the ragged
    # last row rather than stretching to a shape it does not have.
    fitted = max(
        (n for n in range(2, columns + 1) if len(entries) % n == 0),
        default=columns,
    )
    if len(entries) > columns:
        columns = fitted
    global _PAL
    previous, _PAL = _PAL, _STYLES.get(style, _CLAY)
    try:
        rows = math.ceil(len(entries) / columns)
        # Tiles that touch read as one continuous drawing. A margin the width of
        # the caption's own indent is enough to say these are separate proposals
        # without spacing them out into a catalogue.
        pad = 10 if tile[0] >= 400 else 0
        sheet = Image.new(
            "RGB",
            (columns * tile[0] + pad * (columns + 1),
             rows * tile[1] + pad * (rows + 1)),
            _PAL.background,
        )

        for index, (title, source, caption) in enumerate(entries):
            panel = _render_one(source, tile, site_ring=site_ring, title=title, caption=caption)
            column, row = index % columns, index // columns
            sheet.paste(panel, (pad + column * (tile[0] + pad),
                                pad + row * (tile[1] + pad)))
    finally:
        _PAL = previous

    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)
    return output


def render_sequence(
    frames: Sequence[dict[str, Any]],
    output: Path,
    *,
    site_ring: Sequence[tuple[float, float]] | None = None,
    party_edges: Sequence[Sequence[tuple[float, float]]] = (),
    heading: str = "",
    subheading: str = "",
    tile: tuple[int, int] = (400, 480),
) -> Path:
    """One drawing per word of the sentence, all on one scale.

    The shared scale is the whole point. Fitting each panel to its own contents
    makes the mass appear to change size between moves, which is the one thing
    a parti diagram must not say - the reader is being shown what changed, so
    everything that did not change has to sit still.
    """

    if not frames:
        raise ValueError("nothing to render")

    # One bound for every frame, so a move reads as a move.
    world: list[tuple[float, float]] = []
    if site_ring:
        world.extend(_project(x, y, 0.0) for x, y in site_ring)
    for frame in frames:
        source = frame.get("source")
        if source is None:
            continue
        if is_mesh_authoritative(source):
            world.extend(_project(*p) for triangle in physical_triangles(source) for p in triangle)
            continue
        height = float(source.metadata.get("authored_height_m") or 0.0)
        for volume in source.volumes:
            low = float(volume.bottom_fraction) * height
            high = float(volume.top_fraction) * height
            for shape, _colour, _seam in _faces(volume.footprint, low, high, _slope_of(volume, low, high)):
                world.extend(shape)
    if not world:
        raise ValueError("nothing to draw")

    min_x = min(px for px, _py in world)
    max_x = max(px for px, _py in world)
    min_y = min(py for _px, py in world)
    max_y = max(py for _px, py in world)
    span_x = max(max_x - min_x, 1e-6)
    span_y = max(max_y - min_y, 1e-6)

    draw_h = tile[1] - 170
    scale = min((tile[0] - 44) / span_x, (draw_h - 24) / span_y)
    off_x = (tile[0] - span_x * scale) / 2.0
    off_y = 46.0 + (draw_h - span_y * scale) / 2.0

    def to_screen(point: tuple[float, float]) -> tuple[float, float]:
        return (off_x + (point[0] - min_x) * scale, off_y + (point[1] - min_y) * scale)

    head = 78 if heading else 0
    sheet = Image.new("RGB", (len(frames) * tile[0], tile[1] + head), _PAL.background)
    board = ImageDraw.Draw(sheet)

    if heading:
        board.text((26, 22), heading, font=_font(25, bold=True), fill=_PAL.ink)
        if subheading:
            board.text((26, 52), subheading, font=_font(14), fill=_PAL.muted)

    for index, frame in enumerate(frames):
        panel = _render_frame(frame, tile, to_screen, site_ring, party_edges, index + 1)
        sheet.paste(panel, (index * tile[0], head))

    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)
    return output


def _render_frame(
    frame: dict[str, Any],
    tile: tuple[int, int],
    to_screen,
    site_ring: Sequence[tuple[float, float]] | None,
    party_edges: Sequence[Sequence[tuple[float, float]]],
    number: int,
) -> Image.Image:
    panel = Image.new("RGB", tile, _PAL.background)
    draw = ImageDraw.Draw(panel)

    draw.text((22, 18), f"{number:02d}", font=_font(13, bold=True), fill=_PAL.accent)
    draw.text((48, 17), str(frame.get("verb") or ""), font=_font(15, bold=True), fill=_PAL.ink)

    if site_ring:
        draw.polygon([to_screen(_project(x, y, 0.0)) for x, y in site_ring], fill=_PAL.site)
    for edge in party_edges:
        points = [to_screen(_project(x, y, 0.0)) for x, y in edge]
        if len(points) >= 2:
            draw.line(points, fill=_PAL.party_wall, width=4)

    source = frame.get("source")
    if source is not None and is_mesh_authoritative(source):
        paint_mesh(panel, physical_triangles(source), project=_project, to_screen=to_screen,
                   yaw=_YAW, pitch=_PITCH, palette=_PAL, smooth_turn_cos=_SMOOTH_TURN_COS)
        draw = ImageDraw.Draw(panel)
    elif source is not None:
        height = float(source.metadata.get("authored_height_m") or 0.0)
        ordered = sorted(
            source.volumes,
            key=lambda item: (item.bottom_fraction, -item.footprint.centroid.y),
        )
        for volume in ordered:
            low = float(volume.bottom_fraction) * height
            high = float(volume.top_fraction) * height
            for shape, colour, seam in _faces(volume.footprint, low, high, _slope_of(volume, low, high)):
                if len(shape) == 2:
                    draw.line([to_screen(point) for point in shape],
                              fill=_PAL.edge, width=1)
                    continue
                draw.polygon(
                    [to_screen(point) for point in shape], fill=colour,
                    outline=_PAL.edge if seam else colour,
                )

    y = tile[1] - 150
    draw.line([(22, y), (tile[0] - 22, y)], fill=(220, 220, 214), width=1)
    y += 12

    aim = str(frame.get("aim") or "")
    if aim:
        draw.text((22, y), aim, font=_font(12, bold=True), fill=_PAL.accent)
        y += 20

    body = _font(13)
    for line in _wrap(str(frame.get("why") or ""), body, tile[0] - 46)[:5]:
        draw.text((22, y), line, font=body, fill=_PAL.muted)
        y += 19

    numbers = frame.get("numbers")
    if numbers:
        draw.text((22, tile[1] - 30), str(numbers), font=_font(12, bold=True), fill=_PAL.ink)
    return panel


def _plan_key(polygon) -> tuple:
    """What makes two bands the same plan, coarsely enough to survive floats."""

    bounds = tuple(round(value, 2) for value in polygon.bounds)
    return (bounds, round(float(polygon.area), 2), len(polygon.interiors))


def _is_full_band_prism(volume):
    """Recognize exact constant fields without sampling a varying surface.

    Authored constants acquire coordinate wrappers during placement. They
    remain ordinary prisms and retain the established edge/merge rendering.
    """
    from backend.app.modules.design.generation.maas.source_geometry.solid import AffineSurface, ConstantSurface

    def constant(surface, default):
        if surface is None:
            return default
        if isinstance(surface, ConstantSurface):
            return surface.height
        if isinstance(surface, AffineSurface):
            value = constant(surface.surface, None)
            return None if value is None else surface.offset + surface.scale * value
        return None

    return (constant(volume.top_surface, 1.0) == 1.0
            and constant(volume.bottom_surface, 0.0) == 0.0)


def _merged_runs(volumes) -> list[tuple[float, float, Any]]:
    """Consecutive bands with the same plan, drawn as one prism.

    The compiler cuts a mass at every height where any volume starts or stops,
    which is right - it is how a setback is measured and how a court that is
    roofed over still reads as a court below the roof. It is not how a building
    is drawn. A tower crossing thirteen band edges was being drawn as thirteen
    stacked prisms, each with its own outline, so the sheet showed twelve lines
    that are not in the building and the mass read as a pile of slabs.

    Where the plan does not change from one band to the next there is no edge,
    so the run is one volume and gets one outline. Where it does change the line
    stays, because that line is the setback.
    """

    runs: list[tuple[float, float, Any, Any]] = []
    by_plan: dict[tuple, list] = {}
    for volume in volumes:
        # A tilted band never merges and carries itself: the merge yields bare
        # (low, high, footprint) rows, which is exactly how the first gable
        # ever compiled - two wedges, both carrying their tilt - was drawn as
        # two offset flat slabs. The tilt survived compile and died here.
        if ((volume.section_kind() == "surface" and not _is_full_band_prism(volume))
                or float(getattr(volume, "top_drop", 0.0) or 0.0) > 0.0):
            runs.append((float(volume.bottom_fraction), float(volume.top_fraction),
                         volume.footprint, volume))
            continue
        by_plan.setdefault(_plan_key(volume.footprint), []).append(volume)
    for group in by_plan.values():
        group.sort(key=lambda item: item.bottom_fraction)
        low = float(group[0].bottom_fraction)
        high = float(group[0].top_fraction)
        for volume in group[1:]:
            # Contiguous, allowing for the rounding the compiler's fractions
            # carry. A gap means two separate pieces of the same plan - a court
            # roofed over, say - and those are two prisms, not one.
            if float(volume.bottom_fraction) <= high + 1e-4:
                high = max(high, float(volume.top_fraction))
                continue
            runs.append((low, high, group[0].footprint, None))
            low, high = float(volume.bottom_fraction), float(volume.top_fraction)
        runs.append((low, high, group[0].footprint, None))
    return runs


def _draw_plan(draw, source, box, site_ring) -> None:
    """A roof plan beside the axonometric.

    The axonometric hides the one thing a settlement scheme is about. Central
    Beheer came out of the executor as four blocks standing apart - measured,
    four disjoint pieces in plan, and the streets between them are 4.6 m wide -
    and from a single viewpoint the near blocks simply cover them. The gaps are
    in the building and not in the drawing.

    Which is the practice answer as well: SANAA require every option to carry a
    plan, a drawing and a model, and a Korean 배치도 is what a jury reads first.
    One viewpoint is not a massing study.
    """

    left, top, width, height = box
    if is_mesh_authoritative(source):
        projection = actual_xy_projection(source)
        shapes = list(projection.geoms) if hasattr(projection, 'geoms') else [projection]
    else:
        shapes = [row[2] for row in _merged_runs(source.volumes)]
    if not shapes:
        return
    rings = [list(site_ring)] if site_ring else []
    points = [point for shape in shapes for point in shape.exterior.coords]
    points += [point for ring in rings for point in ring]
    xs = [x for x, _y in points]
    ys = [y for _x, y in points]
    span_x = max(max(xs) - min(xs), 1e-6)
    span_y = max(max(ys) - min(ys), 1e-6)
    scale = min(width / span_x, height / span_y)
    off_x = left + (width - span_x * scale) / 2.0
    off_y = top + (height - span_y * scale) / 2.0

    def to_screen(point):
        # North up: screen y grows downward, so the site's y is flipped.
        return (off_x + (point[0] - min(xs)) * scale,
                off_y + (max(ys) - point[1]) * scale)

    for ring in rings:
        draw.polygon([to_screen(point) for point in ring], fill=_PAL.site, outline=None)
    for shape in shapes:
        draw.polygon(
            [to_screen(point) for point in shape.exterior.coords],
            fill=_PAL.roof, outline=_PAL.edge,
        )
        for hole in shape.interiors:
            draw.polygon([to_screen(point) for point in hole.coords], fill=_PAL.site, outline=_PAL.edge)


def _render_one(
    source: SourceMass,
    tile: tuple[int, int],
    *,
    site_ring: Sequence[tuple[float, float]] | None,
    title: str,
    caption: dict[str, Any],
) -> Image.Image:
    panel = Image.new("RGB", tile, _PAL.background)
    draw = ImageDraw.Draw(panel)

    # Read the caption without consuming it. `pop` on the caller's dict meant
    # the sheet ate the thesis and the star, and the per-alternative drawings -
    # rendered afterwards from the same list - came out with the numbers only.
    # The large drawing is the one that gets looked at, so it lost exactly the
    # line it existed to carry.
    body = _font(11)
    mark = "★ " if caption.get("recommended") else ""
    numbers = "  ".join(
        f"{key} {value}"
        for key, value in caption.items()
        if key not in ("thesis", "recommended")
    )
    thesis = str(caption.get("thesis") or "").strip()
    # However many lines the sentence needs. Two was a guess that cut every
    # thesis mid-clause, and a thesis that stops at "so the route through the
    # block is the thing that" argues nothing.
    thesis_lines = _wrap(thesis, body, tile[0] - 20) if thesis else []
    reserve = 46 + 13 * len(thesis_lines)

    height = float(source.metadata.get("authored_height_m") or 0.0)
    # The ground datum: how far the parcel's ground sits above the mass's
    # own base. Zero for every mass that stands on grade; a sunken court or
    # a half-buried bar carries the metres it went down. The site plate is
    # drawn at the datum, over whatever is below it - except inside the pit
    # (the union of sunken footprints), where the ground is open and the
    # walls below show. Nineteen of forty competition winners make their
    # parti in the ground; before this the drawing could not say so.
    datum = float(source.metadata.get("datum_m") or 0.0)
    polygons: list[tuple[list[tuple[float, float]], tuple[int, int, int], bool]] = []

    # Painter's algorithm on the band's own depth: farther bands first, and
    # within a band the lower one first, so an upper volume overlaps the one
    # holding it up rather than the other way round.
    mesh_triangles = physical_triangles(source) if is_mesh_authoritative(source) else None
    ordered = sorted([] if mesh_triangles is not None else _merged_runs(source.volumes),
                     key=lambda item: (
                         item[0],
                         _depth(item[2].centroid.x, item[2].centroid.y),
                     ))
    above: list = []
    pit_parts: list = []
    # A changed footprint is a real band edge. Matching polygon vertices do
    # not establish a loft: discrete rotated boxes also have matching rings.
    # Keep their occupied walls and setbacks. Exact typed surfaces and meshes
    # already take their own rendering paths; only identical plans merge above.
    for low_fraction, high_fraction, footprint, tilted in ordered:
        low = low_fraction * height
        high = high_fraction * height
        slope = _slope_of(tilted, low, high) if tilted is not None else None
        if datum > 1e-6 and low < datum - 1e-6:
            # Below the ground the volume is inside the earth: its walls are
            # the pit's walls, drawn with the earth block below. Only the
            # part above the datum is drawn as building.
            pit_parts.append(footprint)
            if high > datum + 1e-6:
                above.extend(_faces(footprint, datum, high, slope))
            continue
        above.extend(_faces(footprint, low, high, slope))
    if site_ring:
        if datum > 1e-6:
            # The ground is a block, not a sheet: an opaque earth mass from
            # the lowest base up to the datum, with the pit as a hole in it -
            # `_faces` draws walls for holes (inward-facing) and paints the
            # hole in the court tone, which is exactly a sunken court.
            from shapely.geometry import Polygon as _Poly
            from shapely.ops import unary_union as _union
            earth = _Poly(site_ring)
            if pit_parts:
                earth = earth.difference(_union(pit_parts).buffer(0.0))
            pieces = list(earth.geoms) if hasattr(earth, "geoms") else [earth]
            for piece in pieces:
                if piece.is_empty or piece.geom_type != "Polygon":
                    continue
                for shape, colour, seam in _faces(piece, 0.0, datum, None, pit_walls=True):
                    polygons.append((shape, _PAL.site if colour == _PAL.roof else colour, seam))
        else:
            polygons.append(([_project(x, y, 0.0) for x, y in site_ring], _PAL.site, True))
    polygons.extend(above)

    flat = [point for shape, _colour, _seam in polygons for point in shape]
    if mesh_triangles is not None:
        flat.extend(_project(*p) for triangle in mesh_triangles for p in triangle)
    if not flat:
        return panel
    min_x = min(px for px, _py in flat)
    max_x = max(px for px, _py in flat)
    min_y = min(py for _px, py in flat)
    max_y = max(py for _px, py in flat)
    span_x = max(max_x - min_x, 1e-6)
    span_y = max(max_y - min_y, 1e-6)
    # The plan needs its own column, not a corner: dropped on top of the
    # axonometric it lands on the roof, which is the one place a reader is
    # already looking.
    inset = int(tile[0] * 0.26) if tile[0] >= 700 else 0
    gutter = inset + 32 if inset else 0
    scale = min((tile[0] - 30 - gutter) / span_x, (tile[1] - 22 - reserve) / span_y)
    off_x = (tile[0] - gutter - span_x * scale) / 2.0
    off_y = 22.0 + (tile[1] - 22 - reserve - span_y * scale) / 2.0

    def to_screen(point: tuple[float, float]) -> tuple[float, float]:
        return (off_x + (point[0] - min_x) * scale, off_y + (point[1] - min_y) * scale)

    for shape, colour, seam in polygons:
        if len(shape) == 2:
            draw.line([to_screen(point) for point in shape],
                      fill=_PAL.edge, width=1)
            continue
        draw.polygon(
            [to_screen(point) for point in shape], fill=colour,
            outline=_PAL.edge if seam else colour,
        )
    if mesh_triangles is not None:
        paint_mesh(panel, mesh_triangles, project=_project, to_screen=to_screen,
                   yaw=_YAW, pitch=_PITCH, palette=_PAL, smooth_turn_cos=_SMOOTH_TURN_COS)
        draw = ImageDraw.Draw(panel)

    # Room for a plan only where there is room: the contact sheet's tile is a
    # thumbnail and an inset in it would be a smudge. The large drawing per
    # alternative is where the gaps have to be readable.
    if inset:
        draw.text((tile[0] - inset - 16, 38), "배치", font=_font(10), fill=_PAL.muted)
        _draw_plan(draw, source, (tile[0] - inset - 16, 54, inset, inset), site_ring)

    # A recommended option is named as one. RAIC and every feasibility scope say
    # a massing study ends with a recommendation, and a sheet without one is an
    # inventory rather than a proposal.
    heading = _font(12, bold=True)
    draw.text((10, 6), _elide(mark + title, heading, tile[0] - 20), font=heading, fill=_PAL.ink)

    # The thesis, then the numbers. It was the numbers alone, and the numbers
    # are the part a jury does not read: what an option is for is a sentence,
    # and OMA gives every option a name for exactly this reason. The sentence
    # was already being carried on the form as `formal_principle` and thrown
    # away at the tile.
    # A hairline between the drawing and what is said about it. Without it the
    # thesis reads as a caption floating in the same field as the mass, and on
    # a sheet of eight the eye has nothing telling it where one tile ends.
    y = tile[1] - reserve + 8
    draw.line([(10, y - 9), (tile[0] - 10, y - 9)], fill=_PAL.party_wall, width=1)
    # The palette, not two hardcoded greys. These were clay values written into
    # the tile, so the white-model sheet drew its captions in warm brown - the
    # one thing on the page that was not the drawing's own ink.
    for text in thesis_lines:
        draw.text((10, y), text, font=body, fill=_PAL.ink)
        y += 13
    draw.text((10, y + 1), _elide(numbers, body, tile[0] - 20), font=body, fill=_PAL.muted)
    return panel
