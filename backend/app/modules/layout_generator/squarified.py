"""Pack a service band as a squarified treemap.

The generator slices a band into full-depth strips, so every room's depth is the
band depth and its area is bought entirely with width.  On a 9.3 m deep band a
25 m2 restroom becomes 2.69 m x 9.30 m -- aspect 3.46 against its 2.5 limit --
and a 27 m2 pantry 3.20 against 2.0.  Widening the limits to admit those was
what made the validator decorative.

The squarified treemap (Bruls, Huizing & van Wijk 2000) chooses each split
direction from the aspect ratio it would produce rather than always cutting the
same way, which lands the same two rooms at 1.42 and 1.32.  It preserves areas
exactly, so the normative targets from program_prior/sizing.py survive into the
geometry.

Rooms that still miss their gates are reported as violations.  Nothing here
widens a limit to make a room fit.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import squarify

from backend.app.schemas.layout import Point


@dataclass(frozen=True)
class Band:
    """The rectangle a group of rooms has to share."""

    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        for label in ("width", "height"):
            value = getattr(self, label)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"band {label} must be finite and positive")

    @property
    def area_m2(self) -> float:
        return self.width * self.height

    def trim_to_area(self, area_m2: float) -> tuple["Band", "Band | None"]:
        """Split off a sub-band of the given area, trimming the shorter axis.

        Trimming depth rather than length leaves the remainder as a strip
        spanning the band, which is what a corridor serving these rooms is.
        """
        if area_m2 > self.area_m2 + 1e-9:
            raise ValueError("cannot trim a band to more than its own area")
        if area_m2 >= self.area_m2 - 1e-9:
            return self, None
        if self.width >= self.height:
            depth = area_m2 / self.width
            return (
                Band(self.x, self.y, self.width, depth),
                Band(self.x, self.y + depth, self.width, self.height - depth),
            )
        breadth = area_m2 / self.height
        return (
            Band(self.x, self.y, breadth, self.height),
            Band(self.x + breadth, self.y, self.width - breadth, self.height),
        )


@dataclass(frozen=True)
class SpaceRequest:
    """One room's area target and the form gates it must satisfy."""

    space_id: str
    space_type: str
    target_area_m2: float
    min_width: float | None = None
    max_aspect_ratio: float | None = None

    def __post_init__(self) -> None:
        if not math.isfinite(self.target_area_m2) or self.target_area_m2 <= 0:
            raise ValueError(
                f"{self.space_id} target area must be finite and positive"
            )


@dataclass(frozen=True)
class PlacedSpace:
    space_id: str
    space_type: str
    x: float
    y: float
    width: float
    height: float
    target_area_m2: float
    min_width: float | None
    max_aspect_ratio: float | None
    touches_band_edge: bool

    @property
    def area_m2(self) -> float:
        return self.width * self.height

    @property
    def aspect_ratio(self) -> float:
        return max(self.width / self.height, self.height / self.width)

    @property
    def measured_min_width(self) -> float:
        return min(self.width, self.height)

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return (self.x, self.y, self.x + self.width, self.y + self.height)

    @property
    def polygon(self) -> list[Point]:
        x1, y1, x2, y2 = self.bounds
        return [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]


@dataclass(frozen=True)
class PackViolation:
    code: str
    space_id: str
    message: str
    required: float
    measured: float


@dataclass(frozen=True)
class PackResult:
    placements: tuple[PlacedSpace, ...]
    violations: tuple[PackViolation, ...]
    # Band area the program did not claim, shaped as a strip for circulation.
    leftover: Band | None = None

    @property
    def by_id(self) -> dict[str, PlacedSpace]:
        return {item.space_id: item for item in self.placements}

    @property
    def worst_aspect_ratio(self) -> float:
        return max((item.aspect_ratio for item in self.placements), default=0.0)


_EPSILON = 1e-9


SERVED_EDGES = ("left", "right", "top", "bottom")


def pack_squarified(
    spaces: tuple[SpaceRequest, ...],
    band: Band,
    *,
    served_edges: tuple[str, ...] = SERVED_EDGES,
) -> PackResult:
    """Lay the requested spaces out across the band, largest first.

    ``served_edges`` names the band edges a corridor runs along.  With a single
    served edge every room must touch it, so each room's depth is the band depth
    and aspect = depth^2 / area regardless of how the band is cut -- a treemap
    cannot help there, and rooms it places off that edge come back as
    ``room_no_corridor_access`` violations rather than silently unreachable.
    """
    unknown = sorted(set(served_edges) - set(SERVED_EDGES))
    if unknown:
        raise ValueError(f"unknown served edges: {', '.join(unknown)}")
    served = frozenset(served_edges)
    if not spaces:
        return PackResult(placements=(), violations=(), leftover=band)

    by_id = {space.space_id: space for space in spaces}
    if len(by_id) != len(spaces):
        raise ValueError("space ids must be unique within a band")
    requested = sum(space.target_area_m2 for space in spaces)
    if requested > band.area_m2 + _EPSILON:
        raise ValueError(
            f"requested program area {requested:.1f} m2 exceeds the "
            f"{band.area_m2:.1f} m2 band"
        )

    # normalize_sizes would scale the program up to fill the band, inflating a
    # 196 m2 program in a 223 m2 band by 14% and destroying the normative areas
    # the program prior just derived.  Carrying the slack as an extra tile keeps
    # the areas but lets it land mid-band and squeeze its neighbours -- it cost
    # the restroom its aspect limit (2.90 against 2.5).
    #
    # Instead the band is trimmed along its depth to exactly the programmed
    # area.  The rooms pack into the trimmed rectangle and the remaining strip
    # runs the full length of the band, which is the shape a corridor wants.
    packed, leftover = band.trim_to_area(requested)

    ordered = sorted(spaces, key=lambda space: -space.target_area_m2)
    rectangles = squarify.squarify(
        [space.target_area_m2 for space in ordered],
        packed.x,
        packed.y,
        packed.width,
        packed.height,
    )
    tiles = [(space.space_id, space.target_area_m2) for space in ordered]
    placed_by_id = {
        space_id: PlacedSpace(
            space_id=space_id,
            space_type=by_id[space_id].space_type,
            x=rectangle["x"],
            y=rectangle["y"],
            width=rectangle["dx"],
            height=rectangle["dy"],
            target_area_m2=by_id[space_id].target_area_m2,
            min_width=by_id[space_id].min_width,
            max_aspect_ratio=by_id[space_id].max_aspect_ratio,
            touches_band_edge=_touches_band_edge(rectangle, packed, served),
        )
        for (space_id, _), rectangle in zip(tiles, rectangles)
        if space_id is not None
    }
    placements = tuple(placed_by_id[space.space_id] for space in spaces)
    return PackResult(
        placements=placements,
        violations=_violations(placements),
        leftover=leftover,
    )


def _touches_band_edge(
    rectangle: dict,
    band: Band,
    served_edges: frozenset[str],
) -> bool:
    """Whether the rectangle reaches an edge a corridor actually runs along.

    Touching any band edge is not enough: a room on the far side of the band
    from the only corridor cannot be entered.  Checking the perimeter instead of
    the served edges is what let an earlier version of this module report a
    landlocked pantry as reachable.
    """
    x1, y1 = rectangle["x"], rectangle["y"]
    x2, y2 = x1 + rectangle["dx"], y1 + rectangle["dy"]
    reached = {
        "left": abs(x1 - band.x) < _EPSILON,
        "bottom": abs(y1 - band.y) < _EPSILON,
        "right": abs(x2 - (band.x + band.width)) < _EPSILON,
        "top": abs(y2 - (band.y + band.height)) < _EPSILON,
    }
    return any(reached[edge] for edge in served_edges)


def _violations(placements: tuple[PlacedSpace, ...]) -> tuple[PackViolation, ...]:
    violations: list[PackViolation] = []
    for item in placements:
        if not item.touches_band_edge:
            violations.append(
                PackViolation(
                    code="room_no_corridor_access",
                    space_id=item.space_id,
                    message=(
                        f"room '{item.space_id}' reaches no corridor edge of "
                        "the band"
                    ),
                    required=1.0,
                    measured=0.0,
                )
            )
        if (
            item.max_aspect_ratio is not None
            and item.aspect_ratio > float(item.max_aspect_ratio) + _EPSILON
        ):
            violations.append(
                PackViolation(
                    code="room_aspect_ratio",
                    space_id=item.space_id,
                    message=(
                        f"room '{item.space_id}' aspect ratio "
                        f"{item.aspect_ratio:.3f} exceeds "
                        f"{float(item.max_aspect_ratio):.3f}"
                    ),
                    required=float(item.max_aspect_ratio),
                    measured=item.aspect_ratio,
                )
            )
        if (
            item.min_width is not None
            and item.measured_min_width < float(item.min_width) - _EPSILON
        ):
            violations.append(
                PackViolation(
                    code="room_min_width",
                    space_id=item.space_id,
                    message=(
                        f"room '{item.space_id}' width "
                        f"{item.measured_min_width:.3f} m is under "
                        f"{float(item.min_width):.3f} m"
                    ),
                    required=float(item.min_width),
                    measured=item.measured_min_width,
                )
            )
    return tuple(violations)
