from __future__ import annotations

import math

from backend.app.schemas.layout import (
    DoorSwing,
    PlanLine,
    Point,
    StairFlight,
    StairGeometry,
    StairLanding,
)

CONCEPT_DEFAULT_FLOOR_TO_FLOOR_HEIGHT_M = 3.6
CONCEPT_MAX_RISER_HEIGHT_M = 0.18
CONCEPT_TREAD_DEPTH_M = 0.28
CONCEPT_CLEAR_WIDTH_M = 1.2
CONCEPT_LANDING_DEPTH_M = 1.2
CONCEPT_FLIGHT_GAP_M = 0.2
CONCEPT_WALL_ALLOWANCE_M = 0.2


def resolve_floor_height(value: float | None) -> tuple[float, str]:
    if value is None:
        return CONCEPT_DEFAULT_FLOOR_TO_FLOOR_HEIGHT_M, "concept-default"
    if not math.isfinite(value) or value <= 0:
        raise ValueError("floor-to-floor height must be finite and positive")
    return float(value), "project-fact"


def required_stair_enclosure(height_m: float) -> tuple[float, float]:
    risers = math.ceil(height_m / CONCEPT_MAX_RISER_HEIGHT_M)
    first = (risers + 1) // 2
    second = risers - first
    longest_run = max(first - 1, second - 1) * CONCEPT_TREAD_DEPTH_M
    width = (
        2 * CONCEPT_CLEAR_WIDTH_M
        + CONCEPT_FLIGHT_GAP_M
        + CONCEPT_WALL_ALLOWANCE_M
    )
    length = longest_run + 2 * CONCEPT_LANDING_DEPTH_M
    return round(width, 6), round(length, 6)


def create_stair_geometry(
    footprint: tuple[Point, ...],
    *,
    floor_to_floor_height_m: float,
    height_source: str,
    entry_points: tuple[Point, ...] | None = None,
) -> StairGeometry:
    min_x = min(point[0] for point in footprint)
    min_y = min(point[1] for point in footprint)
    max_x = max(point[0] for point in footprint)
    max_y = max(point[1] for point in footprint)
    actual_x = max_x - min_x
    actual_y = max_y - min_y
    required_width, required_length = required_stair_enclosure(
        floor_to_floor_height_m
    )
    if sorted((actual_x, actual_y))[0] + 1e-7 < required_width or sorted(
        (actual_x, actual_y)
    )[1] + 1e-7 < required_length:
        raise ValueError(
            "stair footprint cannot contain the height-derived enclosure "
            f"{required_width:.2f} x {required_length:.2f} m"
        )

    long_x = actual_x >= actual_y
    width = required_width
    length = required_length
    origin_x = min_x + (actual_x - (length if long_x else width)) / 2
    origin_y = min_y + (actual_y - (width if long_x else length)) / 2
    reverse_depth = False
    if entry_points:
        entry_midpoint = (
            sum(point[0] for point in entry_points) / len(entry_points),
            sum(point[1] for point in entry_points) / len(entry_points),
        )
        if long_x:
            reverse_depth = abs(entry_midpoint[0] - max_x) < abs(
                entry_midpoint[0] - min_x
            )
        else:
            reverse_depth = abs(entry_midpoint[1] - max_y) < abs(
                entry_midpoint[1] - min_y
            )

    def local(u: float, d: float) -> Point:
        resolved_d = length - d if reverse_depth else d
        return (
            (origin_x + resolved_d, origin_y + u)
            if long_x
            else (origin_x + u, origin_y + resolved_d)
        )

    def rectangle(u0: float, d0: float, u1: float, d1: float) -> tuple[Point, ...]:
        return (
            local(u0, d0),
            local(u1, d0),
            local(u1, d1),
            local(u0, d1),
        )

    riser_count = math.ceil(
        floor_to_floor_height_m / CONCEPT_MAX_RISER_HEIGHT_M
    )
    first_risers = (riser_count + 1) // 2
    second_risers = riser_count - first_risers
    first_treads = first_risers - 1
    second_treads = second_risers - 1
    first_run = first_treads * CONCEPT_TREAD_DEPTH_M
    second_run = second_treads * CONCEPT_TREAD_DEPTH_M
    run_start = CONCEPT_LANDING_DEPTH_M
    run_end = length - CONCEPT_LANDING_DEPTH_M
    flight_width = CONCEPT_CLEAR_WIDTH_M
    second_u = flight_width + CONCEPT_FLIGHT_GAP_M
    half_height = floor_to_floor_height_m * first_risers / riser_count
    first_direction = (
        ("-x" if reverse_depth else "+x")
        if long_x
        else ("-y" if reverse_depth else "+y")
    )
    second_direction = (
        ("+x" if reverse_depth else "-x")
        if long_x
        else ("+y" if reverse_depth else "-y")
    )
    flights = (
        StairFlight(
            flight_index=1,
            footprint=rectangle(0, run_start, flight_width, run_start + first_run),
            direction=first_direction,
            riser_count=first_risers,
            tread_count=first_treads,
            start_elevation_m=0.0,
            end_elevation_m=half_height,
        ),
        StairFlight(
            flight_index=2,
            footprint=rectangle(
                second_u,
                run_end - second_run,
                second_u + flight_width,
                run_end,
            ),
            direction=second_direction,
            riser_count=second_risers,
            tread_count=second_treads,
            start_elevation_m=half_height,
            end_elevation_m=floor_to_floor_height_m,
        ),
    )
    landings = (
        StairLanding(
            landing_index=1,
            role="floor_lower",
            footprint=rectangle(0, 0, width, CONCEPT_LANDING_DEPTH_M),
            elevation_m=0.0,
        ),
        StairLanding(
            landing_index=2,
            role="intermediate",
            footprint=rectangle(
                0,
                length - CONCEPT_LANDING_DEPTH_M,
                width,
                length,
            ),
            elevation_m=half_height,
        ),
        StairLanding(
            landing_index=3,
            role="floor_upper",
            footprint=rectangle(0, 0, width, CONCEPT_LANDING_DEPTH_M),
            elevation_m=floor_to_floor_height_m,
        ),
    )
    return StairGeometry(
        floor_to_floor_height_m=floor_to_floor_height_m,
        height_source=height_source,
        clear_width_m=CONCEPT_CLEAR_WIDTH_M,
        riser_count=riser_count,
        riser_height_m=floor_to_floor_height_m / riser_count,
        tread_depth_m=CONCEPT_TREAD_DEPTH_M,
        required_enclosure_width_m=required_width,
        required_enclosure_length_m=required_length,
        enclosure_footprint=rectangle(0, 0, width, length),
        flights=flights,
        landings=landings,
    )


def create_door_swing(
    line: PlanLine,
    lower_landing: tuple[Point, ...],
) -> DoorSwing:
    hinge, end = line.points[0], line.points[-1]
    dx = end[0] - hinge[0]
    dy = end[1] - hinge[1]
    candidates = (
        (hinge[0] - dy, hinge[1] + dx),
        (hinge[0] + dy, hinge[1] - dx),
    )
    min_x = min(point[0] for point in lower_landing)
    max_x = max(point[0] for point in lower_landing)
    min_y = min(point[1] for point in lower_landing)
    max_y = max(point[1] for point in lower_landing)
    leaf_end = max(
        candidates,
        key=lambda point: (
            min_x - 1e-7 <= point[0] <= max_x + 1e-7
            and min_y - 1e-7 <= point[1] <= max_y + 1e-7
        ),
    )
    return DoorSwing(
        hinge=hinge,
        leaf_end=leaf_end,
        angle_degrees=90.0,
        direction=(
            "counterclockwise" if leaf_end == candidates[0] else "clockwise"
        ),
        target_landing_role="floor_lower",
    )
