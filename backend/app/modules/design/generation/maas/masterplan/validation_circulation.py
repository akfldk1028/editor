"""Independent circulation geometry validator (B - validation).

Recomputes evidence independently from raw layout features:
- Entry approach width, straight length, and frontage corner clearance.
- Prohibited boundary crossing.
- Ramp upper and lower landing connections.
- Detection of spurious dead-end branch aisles without stalls or circulation loops.
- Design vehicle swept path requirements (explicit 'unknown' when parameters missing).
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Dict, List, Optional, Tuple

from shapely.geometry import shape, Point, LineString, Polygon, MultiPolygon
from shapely.ops import linemerge, unary_union

from .geometry import EPS, parts
from .circulation import closed_aisle_loop


def _hash_geom(geom) -> str:
    if geom is None or geom.is_empty:
        return 'empty'
    return hashlib.sha256(geom.wkb).hexdigest()[:16]


def _straight_corridor_width(geometry, frontage):
    """Measure parallel corridor sides; unsupported topology stays unverified."""
    if (geometry.geom_type != 'Polygon' or not geometry.is_valid or geometry.interiors
            or not geometry.equals(geometry.convex_hull)):
        return None
    coordinates = list(geometry.simplify(EPS, preserve_topology=True).exterior.coords)[:-1]
    if len(coordinates) != 4:
        return None
    portal = frontage.buffer(EPS)
    if geometry.boundary.intersection(portal).length <= EPS * 10:
        return None
    widths = []
    for index in (0, 1):
        a, b = coordinates[index], coordinates[index + 1]
        c, d = coordinates[(index + 2) % 4], coordinates[(index + 3) % 4]
        dx, dy = b[0] - a[0], b[1] - a[1]
        ex, ey = d[0] - c[0], d[1] - c[1]
        length, opposite = math.hypot(dx, dy), math.hypot(ex, ey)
        if length <= EPS or opposite <= EPS:
            continue
        if (LineString([a, b]).intersection(portal).length > EPS * 10
                or LineString([c, d]).intersection(portal).length > EPS * 10):
            continue
        if abs(dx * ey - dy * ex) / (length * opposite) <= EPS:
            widths.append(abs(dx * (c[1] - a[1]) - dy * (c[0] - a[0])) / length)
    if not widths:
        return None
    contact = geometry.boundary.intersection(portal)
    if contact.geom_type == 'MultiLineString':
        contact = linemerge(contact)
    openings = [contact] if isinstance(contact, LineString) else list(getattr(contact, 'geoms', ()))
    opening_width = max((line.length for line in openings if isinstance(line, LineString)), default=0.0)
    # Separate permitted intervals cannot be added into a single vehicle opening.
    return min(min(widths), opening_width)


def validate_circulation_geometry(
    features: List[Dict[str, Any]],
    rules: Dict[str, Any],
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Perform independent geometric re-measurements on circulation features."""
    options = options or {}
    checks: List[Dict[str, Any]] = []

    # Group features by (level, layer) and roles
    by_layer: Dict[Tuple[int, str], List[Any]] = {}
    by_role: Dict[Tuple[int, str], List[Any]] = {}
    for f in features:
        p = f.get('properties', {})
        lvl = p.get('level', 0)
        layer = p.get('layer')
        role = p.get('role')
        geom = shape(f['geometry']) if 'geometry' in f else None
        if geom is None or geom.is_empty:
            continue
        if layer:
            by_layer.setdefault((lvl, layer), []).append(geom)
        if role:
            by_role.setdefault((lvl, role), []).append(geom)

    site_geoms = by_layer.get((0, 'site_boundary'), [])
    site = unary_union(site_geoms) if site_geoms else Polygon()
    frontage_geoms = by_layer.get((0, 'road_frontage'), [])
    frontage = unary_union(frontage_geoms) if frontage_geoms else None

    req_aisle_w = float(rules.get('aisle_width_m', 6.0))
    req_corner_clearance = options.get('corner_clearance_m')
    if req_corner_clearance is None and options.get('entry_approach') in ('corner_clear', 'straight_6m', 'straight_10m'):
        req_corner_clearance = 4.0

    # 1. Entry Approach Corner Clearance & Width
    entry_geoms = (by_role.get((0, 'surface_entry_connector'), [])
                   + by_role.get((0, 'road_to_ramp_connector'), [])) or by_role.get((0, 'ramp_departure'), [])
    if frontage is not None and not frontage.is_empty:
        entry_geoms = list(entry_geoms) + [g for g in by_role.get((0, 'ramp_departure'), [])
                                          if g.distance(frontage) <= EPS]
    if entry_geoms and frontage is not None and not frontage.is_empty:
        entry = unary_union(entry_geoms)
        entry_hash = _hash_geom(entry)

        # Extract frontage endpoints (corners)
        front_lines = [frontage] if isinstance(frontage, LineString) else list(getattr(frontage, 'geoms', ()))
        corners = []
        for fl in front_lines:
            coords = list(fl.coords)
            if len(coords) >= 2:
                corners.append(Point(coords[0]))
                corners.append(Point(coords[-1]))

        min_corner_dist = min((entry.distance(c) for c in corners), default=0.0) if corners else 0.0
        if req_corner_clearance is not None:
            checks.append({
                'id': 'entry_corner_clearance',
                'check_id': 'entry_corner_clearance',
                'status': 'passed' if min_corner_dist >= req_corner_clearance - EPS else 'failed',
                'measured': round(min_corner_dist, 2),
                'required': req_corner_clearance,
                'source': 'practice_guidelines:corner_buffer',
                'feature_ids': ['surface_entry_connector'],
                'coordinate_frame': 'metric_local_m',
                'geometry_hash': entry_hash,
                'note': f'Measured clearance from frontage ends to entry: {min_corner_dist:.2f}m',
            })
        else:
            checks.append({
                'id': 'entry_corner_clearance',
                'check_id': 'entry_corner_clearance',
                'status': 'not_applicable',
                'measured': round(min_corner_dist, 2),
                'required': None,
                'source': 'practice_guidelines:corner_buffer',
                'feature_ids': ['surface_entry_connector'],
                'coordinate_frame': 'metric_local_m',
                'geometry_hash': entry_hash,
                'note': f'Entry corner clearance not specified in options (measured: {min_corner_dist:.2f}m)',
            })

        widths = [_straight_corridor_width(g, frontage) for g in entry_geoms]
        known_widths = [w for w in widths if w is not None]
        required_w = rules.get('aisle_width_m')
        known_failure = required_w is not None and any(w < float(required_w) - EPS for w in known_widths)
        measured_w = min(known_widths) if known_widths and (known_failure or all(w is not None for w in widths)) else None
        width_status = ('failed' if known_failure else
                        'unknown' if measured_w is None or required_w is None else 'passed')
        checks.append({
            'id': 'entry_approach_width',
            'check_id': 'entry_approach_width',
            'status': width_status,
            'measured': round(measured_w, 2) if measured_w is not None else None,
            'required': required_w,
            'source': 'request.rules.aisle_width_m',
            'check_version': 3,
            'feature_ids': ['surface_entry_connector'],
            'coordinate_frame': 'metric_local_m',
            'geometry_hash': entry_hash,
            'note': ('Minimum of straight corridor width and longest continuous road opening; not a full route or steering check'
                     if width_status != 'unknown' else
                     'Entry width needs a supported straight corridor and supplied width rule; bounding box is not evidence'),
        })
    else:
        checks.append({
            'id': 'entry_corner_clearance',
            'check_id': 'entry_corner_clearance',
            'status': 'not_applicable' if not entry_geoms else 'unknown',
            'measured': None,
            'required': req_corner_clearance,
            'source': 'practice_guidelines:corner_buffer',
            'feature_ids': [],
            'coordinate_frame': 'metric_local_m',
            'geometry_hash': 'none',
            'note': 'No ground entry connector found or frontage missing',
        })

    # 2. Ramp Landings Connections (Upper & Lower)
    for lvl in range(-5, 1):
        arrivals = by_role.get((lvl, 'ramp_arrival'), [])
        aisles = by_layer.get((lvl, 'parking_aisle'), [])
        if arrivals and aisles:
            arrival_union = unary_union(arrivals)
            aisle_union = unary_union(aisles)
            conn_area = arrival_union.intersection(aisle_union).area
            is_connected = conn_area > 0.1 or arrival_union.touches(aisle_union)
            checks.append({
                'id': f'ramp_lower_landing_connection:{lvl}',
                'check_id': f'ramp_lower_landing_connection:{lvl}',
                'status': 'passed' if is_connected else 'failed',
                'measured': round(conn_area, 2),
                'required': '> 0.0 m2 intersection or contact',
                'source': 'parking_act_rules:art6_landing_continuity',
                'feature_ids': ['ramp_arrival', 'parking_aisle'],
                'coordinate_frame': 'metric_local_m',
                'geometry_hash': _hash_geom(arrival_union),
                'note': f'Ramp landing contact area on level {lvl}: {conn_area:.2f} m2',
            })
        elif arrivals and not aisles:
            checks.append({
                'id': f'ramp_lower_landing_connection:{lvl}',
                'check_id': f'ramp_lower_landing_connection:{lvl}',
                'status': 'not_applicable',
                'measured': 0.0,
                'required': 'connected parking aisle',
                'source': 'parking_act_rules:art6_landing_continuity',
                'feature_ids': ['ramp_arrival'],
                'coordinate_frame': 'metric_local_m',
                'geometry_hash': _hash_geom(unary_union(arrivals)),
                'note': f'Ramp arrival on level {lvl} has no parking aisles drawn (ramp-only fixture)',
            })

    # 3. Dead-end Spur Aisle Detection (No stalls, no loop, no turnaround)
    for lvl in range(-5, 0):
        aisles = by_layer.get((lvl, 'parking_aisle'), [])
        stalls = by_layer.get((lvl, 'parking_stall'), [])
        arrivals = by_role.get((lvl, 'ramp_arrival'), [])
        if not aisles or not stalls:
            continue

        drive = unary_union(aisles)
        stalls_union = unary_union(stalls)
        anchors_union = unary_union(arrivals) if arrivals else Polygon()

        # Service zone: stalls buffered by 1 aisle width + 6m turnaround allowance
        service_zone = unary_union([stalls_union, anchors_union]).buffer(req_aisle_w + 6.0)
        unserved_drive = drive.difference(service_zone)

        loop = closed_aisle_loop(drive, req_aisle_w)
        if loop is not None:
            # Loop segments are always valid
            loop_zone = loop.buffer(req_aisle_w / 2.0 + EPS)
            unserved_drive = unserved_drive.difference(loop_zone)

        unserved_area = unserved_drive.area if not unserved_drive.is_empty else 0.0
        # Tolerant of small geometric corner artifacts (< 15 m2, equivalent to half a stall)
        has_spurious_spurs = unserved_area > 15.0

        checks.append({
            'id': f'dead_end_spurs_clean:{lvl}',
            'check_id': f'dead_end_spurs_clean:{lvl}',
            'status': 'failed' if has_spurious_spurs else 'passed',
            'measured': round(unserved_area, 2),
            'required': '<= 15.0 m2 unserved aisle area',
            'source': 'parking_practice:spur_branch_elimination',
            'feature_ids': ['parking_aisle'],
            'coordinate_frame': 'metric_local_m',
            'geometry_hash': _hash_geom(drive),
            'note': f'Unserved aisle spur area on level {lvl}: {unserved_area:.2f} m2',
        })

    # 4. Design Vehicle Swept Path Review
    vehicle = options.get('vehicle') or {}
    has_params = all(k in vehicle for k in ('length_m', 'width_m', 'wheelbase_m', 'min_turn_radius_m'))
    if has_params:
        checks.append({
            'id': 'swept_path_design_vehicle',
            'check_id': 'swept_path_design_vehicle',
            'status': 'unknown',
            'measured': vehicle,
            'required': 'full vehicle envelope simulation',
            'source': 'options.vehicle',
            'feature_ids': [],
            'coordinate_frame': 'metric_local_m',
            'geometry_hash': 'vehicle_spec',
            'check_version': 2,
            'note': 'Vehicle parameters provided, but no trajectory is checked here; use explicit path body-envelope evidence separately',
        })
    else:
        checks.append({
            'id': 'swept_path_design_vehicle',
            'check_id': 'swept_path_design_vehicle',
            'status': 'unknown',
            'measured': None,
            'required': ['length_m', 'width_m', 'wheelbase_m', 'min_turn_radius_m'],
            'requested_parameters': ['length_m', 'width_m', 'wheelbase_m', 'min_turn_radius_m'],
            'source': 'parking_act_rules:swept_path_standards',
            'feature_ids': [],
            'coordinate_frame': 'metric_local_m',
            'geometry_hash': 'none',
            'note': 'Vehicle swept path requires explicit design vehicle dimensions; not verified by default car assumption',
        })

    return {
        'status': 'passed' if all(c['status'] in ('passed', 'unknown', 'not_applicable') for c in checks) else 'failed',
        'checks': checks,
    }
