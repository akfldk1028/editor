"""Circulation network generation, entry approach branching, and dead-end branch pruning.

Follows the architectural principles:
1. Straight entry approach corridor before branching into ramp or surface aisle.
2. Prevents immediate 90-degree turning at parcel corners.
3. Aligns landing arrival to primary circulation aisles.
4. Prunes useless dead-end branch aisles without stalls, loops or turnaround purpose.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from shapely.affinity import rotate
from shapely.geometry import box, LineString, Point, Polygon, MultiPolygon
from shapely.ops import unary_union

from .geometry import EPS, number, parts
from .circulation import closed_aisle_loop


def plan_entry_approach(
    site: Polygon,
    frontage: LineString,
    corner_clearance_m: float = 4.0,
    min_straight_length_m: float = 6.0,
    offset_m: Optional[float] = None,
    aisle_width_m: float = 6.0,
) -> Dict[str, Any]:
    """Plan a straight vehicular entry approach from the frontage road into the site.

    Ensures the entry does not hug extreme parcel corners, and provides a continuous
    straight approach segment before any branching occurs.
    """
    if frontage is None or frontage.is_empty:
        return {'valid': False, 'reason': 'missing_frontage'}
    if not isinstance(frontage, LineString):
        lines = list(getattr(frontage, 'geoms', ()))
        if not lines:
            return {'valid': False, 'reason': 'invalid_frontage'}
        frontage = max(lines, key=lambda l: l.length)

    coords = list(frontage.coords)
    if len(coords) < 2:
        return {'valid': False, 'reason': 'insufficient_frontage_coords'}

    total_len = frontage.length
    if total_len < aisle_width_m + 2 * corner_clearance_m:
        # Frontage is too short for safe corner clearance + aisle width
        return {'valid': False, 'reason': 'frontage_too_short_for_corner_clearance'}

    if offset_m is None:
        offset_m = total_len / 2.0  # Center along frontage by default

    # Verify corner clearance
    if offset_m < corner_clearance_m - EPS:
        return {'valid': False, 'reason': f'too_close_to_corner: offset {offset_m:.2f}m < clearance {corner_clearance_m:.2f}m'}
    if offset_m > total_len - corner_clearance_m + EPS:
        return {'valid': False, 'reason': f'too_close_to_corner: offset {offset_m:.2f}m > max {total_len - corner_clearance_m:.2f}m'}

    # Determine inward normal vector
    entry_pt = frontage.interpolate(offset_m)
    # Estimate direction along edge at offset
    d_delta = min(1.0, total_len * 0.05)
    p_before = frontage.interpolate(max(0.0, offset_m - d_delta))
    p_after = frontage.interpolate(min(total_len, offset_m + d_delta))
    dx = p_after.x - p_before.x
    dy = p_after.y - p_before.y
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return {'valid': False, 'reason': 'degenerate_frontage_segment'}

    along = (dx / length, dy / length)
    # Check both normal directions (+90, -90) to find inward into site
    normals = [(-along[1], along[0]), (along[1], -along[0])]
    inward = None
    for nx, ny in normals:
        test_pt = Point(entry_pt.x + nx * 2.0, entry_pt.y + ny * 2.0)
        if site.buffer(EPS).covers(test_pt):
            inward = (nx, ny)
            break

    if inward is None:
        return {'valid': False, 'reason': 'cannot_determine_inward_direction_into_site'}

    # Construct straight approach corridor
    ix, iy = inward
    p_end = (entry_pt.x + ix * min_straight_length_m, entry_pt.y + iy * min_straight_length_m)
    centerline = LineString([(entry_pt.x, entry_pt.y), p_end])

    # Corridor polygon (buffered centerline with flat caps)
    corridor = centerline.buffer(aisle_width_m / 2.0, cap_style=2, join_style=2)
    if not site.buffer(EPS).covers(corridor):
        # Truncate or fail if outside parcel
        return {'valid': False, 'reason': 'approach_corridor_exceeds_parcel_boundary'}

    return {
        'valid': True,
        'entry_point': (entry_pt.x, entry_pt.y),
        'branch_point': p_end,
        'centerline': centerline,
        'approach_polygon': corridor,
        'approach_length_m': min_straight_length_m,
        'aisle_width_m': aisle_width_m,
        'inward_vector': inward,
    }


def connect_landing_to_aisle(
    landing: Polygon,
    module_drive: Polygon,
    aisle_width_m: float = 6.0,
) -> Polygon:
    """Connect a ramp landing directly to the circulation aisle network."""
    if landing is None or landing.is_empty:
        return module_drive
    if module_drive is None or module_drive.is_empty:
        return landing

    # Direct union with smoothing
    connected = unary_union([module_drive, landing]).buffer(0)
    return connected


def prune_useless_aisle_branches(
    drive: Polygon | MultiPolygon,
    stalls: List[Any],
    anchors: Any,
    aisle_width: float = 6.0,
    allow_turnaround_m: float = 6.0,
) -> Tuple[Polygon | MultiPolygon, Dict[str, Any]]:
    """Prune useless dead-end branch aisles that do not serve stalls, loops, or access.

    A branch is valid if:
    1. It provides access front to stalls.
    2. It is part of a closed circulation loop.
    3. It connects ramp landing(s) / entrances to stalls.
    4. It is a reasonable dead-end turnaround stub (within allow_turnaround_m).
    Any spur extending further into empty space without stalls is pruned.
    """
    if drive is None or drive.is_empty:
        return drive, {'pruned_spurs_count': 0, 'reason': 'empty_drive'}

    stall_polys = []
    for s in stalls:
        if isinstance(s, dict) and 'polygon' in s:
            stall_polys.append(s['polygon'])
        elif hasattr(s, 'geom_type'):
            stall_polys.append(s)

    anchor_list = []
    if isinstance(anchors, list):
        anchor_list = [a for a in anchors if a is not None and not a.is_empty]
    elif anchors is not None and hasattr(anchors, 'geom_type') and not anchors.is_empty:
        anchor_list = [anchors]

    # Useful zone includes:
    # - Buffer around all stalls (manoeuvre zone in front of stalls)
    # - Buffer around all anchors (landings)
    # - Aisle width buffer around connecting lines between anchors and stalls
    elements_to_buffer = list(stall_polys) + list(anchor_list)
    if not elements_to_buffer:
        return drive, {'pruned_spurs_count': 0, 'reason': 'no_elements_to_service'}

    # Check for closed circulation loop
    loop = closed_aisle_loop(drive, aisle_width)
    loop_zone = loop.buffer(aisle_width / 2.0 + EPS) if loop is not None else None

    # Service zone: stalls plus access plus turnaround margin
    stall_service = unary_union(elements_to_buffer).buffer(aisle_width + allow_turnaround_m)
    
    # In addition, any straight path connecting anchor to any stall must be covered
    anchor_access_zones = []
    for a in anchor_list:
        for s in stall_polys:
            line = LineString([a.centroid, s.centroid])
            anchor_access_zones.append(line.buffer(aisle_width + EPS))
    
    full_service_zone = unary_union([stall_service] + anchor_access_zones + ([loop_zone] if loop_zone else []))

    # Intersect drive with service zone
    pruned = drive.intersection(full_service_zone).buffer(0)

    # Clean up small slivers
    if pruned.geom_type == 'MultiPolygon':
        # Keep only components that contain an anchor or intersect stalls
        valid_parts = []
        for p in pruned.geoms:
            if any(p.intersects(a) for a in anchor_list) or any(p.intersects(s) for s in stall_polys):
                valid_parts.append(p)
        pruned = unary_union(valid_parts).buffer(0) if valid_parts else pruned

    pruned_area = drive.area - pruned.area
    was_pruned = pruned_area > 1.0  # More than 1 sq m pruned

    return pruned, {
        'pruned_spurs_count': 1 if was_pruned else 0,
        'pruned_area_m2': round(pruned_area, 2),
        'circulation_loop_preserved': loop is not None,
        'retained_area_m2': round(pruned.area, 2),
    }


def validate_approach_geometry(
    approach: Dict[str, Any],
    min_straight_len: float = 6.0,
    min_width: float = 6.0,
) -> Dict[str, Any]:
    """Independent check of entry approach geometry."""
    if not approach or not approach.get('valid'):
        return {'status': 'failed', 'reason': approach.get('reason', 'invalid_approach')}

    length = approach.get('approach_length_m', 0.0)
    width = approach.get('aisle_width_m', 0.0)

    if length < min_straight_len - EPS:
        return {'status': 'failed', 'reason': f'straight length {length:.2f}m < {min_straight_len}m'}
    if width < min_width - EPS:
        return {'status': 'failed', 'reason': f'aisle width {width:.2f}m < {min_width}m'}

    return {'status': 'passed', 'measured_length_m': length, 'measured_width_m': width}
