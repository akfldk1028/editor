"""Bounded internal-aisle ramp proposals, reserving real surface circulation.

The existing row is a proposal, not an immutable stall count. A ramp removes
every intersected bay and sloping run from surface circulation. Only a full
width connection from the original public-road frontage is retained.
"""
from shapely.geometry import LineString
from shapely.ops import unary_union

from backend.app.modules.design.generation.maas.masterplan.bounded_packing import _width_connected
from backend.app.modules.design.generation.maas.masterplan.geometry import EPS, parts
from backend.app.modules.design.generation.maas.masterplan.ramps import curved_ramp_candidates


def reserve_ramp(row, ramp, road, aisle_width):
    sloping = ramp['polygon'].difference(ramp['upper_landing'])
    drive = unary_union([row['drive'].difference(sloping), ramp['upper_landing']]).buffer(0)
    # Cutting a ramp can strand empty drive fragments that stall reachability
    # alone does not inspect. Keep actual geometry connected to the road.
    reachable = unary_union([p for p in parts(drive.buffer(EPS)) if p.distance(road) <= EPS])
    drive = drive.intersection(reachable)
    stalls = [s for s in row['stalls']
              if s['polygon'].intersection(ramp['polygon']).area <= EPS
              and drive.buffer(EPS).covers(s['front'])]
    # Include the upper landing as an additional reachable manoeuvre cell.
    # Connectivity to an isolated landing must not pass just because all bays
    # remain reachable on the other side of a removed ramp segment.
    if not _width_connected({'drive': drive, 'stalls': [*stalls, {'front': ramp['upper_landing']}]},
                            [road], aisle_width):
        return None
    return {**row, 'drive': drive, 'stalls': stalls, 'ramp': ramp,
            'provided': len(stalls), 'accessible': sum(s['type'] == 'accessible' for s in stalls),
            'removed_for_ramp': len(row['stalls']) - len(stalls)}


def aisle_ramp_candidates(site, rows, obstacles, road, rules, height, *, limit=12,
                          occupied=None, slab_soffit_z_m=None, required_height_m=None,
                          footprint=None, accept_ramp=None):
    """Try up to three distinct row orientations and four long aisle edges each.

    Every numerical limit is a search budget, not a geometry or legal rule.
    Ramp dimensions and profile come unchanged from the passed rule snapshot.
    """
    accept = None
    ramp_obstacles = obstacles
    if occupied is not None and not occupied.is_empty:
        if slab_soffit_z_m is not None and required_height_m is not None:
            from backend.app.modules.design.generation.maas.masterplan.ramp_overhead import overhead_clearance
            accept = lambda ramp: overhead_clearance(ramp, occupied, slab_soffit_z_m,
                                                      required_height_m)['passed']
        else:
            ramp_obstacles = unary_union([obstacles, occupied])
    selected, seen = [], set()
    for row in sorted(rows, key=lambda r: -r['provided']):
        if not _width_connected(row, [road], float(rules['aisle_width_m'])):
            continue
        orientation = round(float(row['angle_deg']) / 5)
        if orientation in seen:
            continue
        seen.add(orientation)
        selected.append(row)
        if len(selected) == 3:
            break
    results = []
    for row in selected:
        edges = []
        for polygon in parts(row['drive']):
            coords = list(polygon.exterior.coords)
            edges.extend(LineString([a, b]) for a, b in zip(coords, coords[1:]))
        edges = sorted(edges, key=lambda e: -e.length)[:4]
        for edge in edges:
            def usable(ramp):
                return ((accept is None or accept(ramp)) and
                        (accept_ramp is None or accept_ramp(ramp)) and
                        reserve_ramp(row, ramp, road, float(rules['aisle_width_m'])) is not None)
            for ramp in curved_ramp_candidates(site, edge, ramp_obstacles, rules, height,
                                               turns=(45., 90., 180.), limit=3, accept=usable):
                proposal = reserve_ramp(row, ramp, road, float(rules['aisle_width_m']))
                if proposal is not None:
                    proposal['ramp']['shape'] = 'curved'
                    if accept is not None:
                        proposal['ramp']['overhead_soffit_z_m'] = slab_soffit_z_m
                        proposal['ramp']['overhead_clearance'] = overhead_clearance(
                            ramp, occupied, slab_soffit_z_m, required_height_m)
                        proposal['ramp']['overhead_section_inputs'] = {
                            'slab_soffit_z_m': slab_soffit_z_m, 'required_height_m': required_height_m,
                            'assumption': 'uniform_slab_soffit; beam verification remains pending'}
                    if footprint is not None:
                        proposal['ramp']['share_under_footprint'] = ramp['polygon'].intersection(footprint).area / ramp['polygon'].area
                        proposal['basement'] = unary_union([footprint, ramp['polygon']]).convex_hull.intersection(site)
                    results.append(proposal)
        if len(results) >= limit:
            break
    return sorted(results, key=lambda r: (-r['provided'], r['removed_for_ramp']))[:limit]
