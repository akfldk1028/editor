"""Bounded alternative mass placements around parking module dimensions.

These are proposals, not edits to authored MassAgent geometry. Target area is
preserved; clipping is never used to make an undersized building appear feasible.
All dimensions come from the request's programme and parking rules.
"""
from __future__ import annotations

import math
from shapely.affinity import rotate
from shapely.geometry import box
from backend.app.modules.design.generation.maas.masterplan.geometry import EPS, parts
from backend.app.modules.design.generation.maas.masterplan.pedestrian import pedestrian_reservation, exclude_reserved_stalls
from backend.app.modules.design.generation.maas.masterplan.layout_axis import layout_axis_angle


def footprint_candidates(buildable, target, front, module_depth, limit=32, *, angle_deg=None, aspect_ratio=None):
    if target <= 0 or target > buildable.area + EPS:
        return []
    if front is not None and front.geom_type == 'LineString':
        a, b = list(front.coords)[0], list(front.coords)[-1]
    else:
        a, b = list(buildable.minimum_rotated_rectangle.exterior.coords)[:2]
    angle = math.degrees(math.atan2(b[1]-a[1], b[0]-a[0])) if angle_deg is None else angle_deg
    host = rotate(buildable, -angle, origin=(0,0))
    edge = rotate(front, -angle, origin=(0,0)) if front is not None else None
    families, seen = [], set()
    for component in parts(host):
        x0,y0,x1,y1 = component.bounds
        width, depth = x1-x0, y1-y0
        # Wide bars, compact plates and module-proportioned plates compete.
        widths = [width, width*.85, width*.7, math.sqrt(target),
                  target/module_depth, target/(2*module_depth)] if module_depth else [width, math.sqrt(target)]
        if aspect_ratio is not None:
            # An explicit design family, never a score or parcel-specific preferred mass.
            widths = [math.sqrt(target * aspect_ratio)]
        front_high = edge is None or edge.centroid.y >= component.centroid.y
        for w in widths:
            if w <= 0 or w > width+EPS:
                continue
            d = target/w
            if d > depth+EPS:
                continue
            family=[]
            fractions = [0, .1, .25, .5, .75, .9, 1]
            ys = [y0+(depth-d)*f for f in (reversed(fractions) if front_high else fractions)]
            for y in ys:
                for x in [x0+(width-w)*f for f in reversed(fractions)]:
                    p = box(x,y,x+w,y+d)
                    if not component.buffer(EPS).covers(p):
                        continue
                    world = rotate(p, angle, origin=(0,0))
                    key=tuple(round(v,5) for v in p.bounds)
                    if key in seen:
                        continue
                    seen.add(key)
                    family.append(world)
            if family:
                families.append(family)
    out=[]
    for index in range(max(map(len,families),default=0)):
        for family in families:
            if index<len(family):
                out.append(family[index])
                if len(out)>=limit:
                    return out
    return out


def piloti_ground_variants(site, footprint, stall_length, aisle_width):
    """Enclosed-ground variants of a generated building: upper floors keep the footprint, the
    ground floor gives up a strip along the face with the most open parcel ground so a stall
    row (or a row and its aisle) can pass beneath. The practice reference (고산 ALT1) does
    exactly this under its road-side wing and reaches 30 surface stalls where the same
    building with a fully enclosed ground floor reaches 22. Depths come from the rules, the
    face from the parcel; nothing here is parcel-specific. Yields (strip_depth_m, ground)."""
    from shapely.geometry import Polygon
    mrr = footprint.minimum_rotated_rectangle
    rect = list(mrr.exterior.coords)
    cx, cy = mrr.centroid.x, mrr.centroid.y
    for depth in (stall_length, stall_length + aisle_width):
        best = None
        for a, b in zip(rect, rect[1:]):
            dx, dy = b[0]-a[0], b[1]-a[1]
            length = math.hypot(dx, dy)
            if length <= EPS:
                continue
            nx, ny = dy/length, -dx/length
            # outward = away from the rectangle's centre; a probe point inside the mass is wrong
            # on a notched (concave) footprint whose edge midpoint lies in the notch
            if (cx - (a[0]+b[0])/2) * nx + (cy - (a[1]+b[1])/2) * ny > 0:
                nx, ny = -nx, -ny
            outside = Polygon([a, b, (b[0]+nx*depth, b[1]+ny*depth), (a[0]+nx*depth, a[1]+ny*depth)])
            free = outside.intersection(site).difference(footprint).area
            inside = Polygon([a, b, (b[0]-nx*depth, b[1]-ny*depth), (a[0]-nx*depth, a[1]-ny*depth)])
            if best is None or free > best[0]:
                best = (free, inside)
        if best is None:
            continue
        ground = footprint.difference(best[1])
        ground = max(parts(ground), key=lambda g: g.area, default=Polygon())
        if ground.area > EPS and footprint.area - ground.area > EPS:
            yield depth, ground


def select_joint_layout(request, solve):
    """Screen equal-area proposals, then compare complete ground/basement plans.

    A coarse surface screen is only a shortlist, never the feasibility verdict.
    The original proposal remains in the final competition. Fixed authored mass,
    core and partial-piloti input are never silently relocated by this search.
    In the placement stage the engine's own building zone also competes against
    its piloti variants (`piloti_ground_variants`); an authored ground footprint
    is never replaced.
    """
    import copy
    from shapely.geometry import shape, mapping, Polygon
    from backend.app.modules.design.generation.maas.masterplan.geometry import digest
    from backend.app.modules.design.generation.maas.masterplan.rows import row_candidates
    opts = request.get('options', {})
    explicit_angle = layout_axis_angle(request)
    baseline = solve(copy.deepcopy(request))
    if baseline.get('planner_invoked') is False:
        return baseline
    placement_stage = opts.get('planning_stage') == 'placement'
    if (request.get('footprint') or request.get('ground_footprint') or request.get('core')
            or request.get('columns') or opts.get('joint_placement_search') is False
            or (opts.get('target_surface_stalls') is None and not placement_stage)):
        return baseline
    site = shape(request['site'])
    if site.area >= 10000:
        return baseline
    rules = request.get('rules', {})
    if not all(rules.get(k) for k in ('stall_width_m','stall_length_m','aisle_width_m',
                                     'accessible_width_m','accessible_length_m')):
        return baseline
    if not request.get('frontage'):
        return baseline
    front = shape(request['front_frontage']) if request.get('front_frontage') else None
    road = shape(request['frontage'])
    host = shape(request.get('buildable') or request['site'])
    pedestrian=pedestrian_reservation(request)
    host=host.difference(pedestrian['reserved'])
    target = baseline['metrics']['building_footprint_m2']
    module = 2*rules['stall_length_m']+rules['aisle_width_m']
    layouts=[baseline]
    generated = next((shape(f['geometry']) for f in baseline.get('features', [])
                      if f.get('properties', {}).get('layer') == 'building_footprint'), None)
    surface_possible = opts.get('parking_strategy') != 'basement' and opts.get('max_surface_stalls') != 0
    if placement_stage and surface_possible and generated is not None and not generated.is_empty:
        # the face is chosen on ground a car may actually use: the parcel less the vehicle-blocked
        # pedestrian reservation
        for depth, ground in piloti_ground_variants(site.difference(pedestrian['vehicle_blocked']), generated,
                                                    float(rules['stall_length_m']), float(rules['aisle_width_m'])):
            candidate = copy.deepcopy(request)
            candidate['footprint'] = mapping(generated)
            candidate['ground_footprint'] = mapping(ground)
            result = solve(candidate)
            for f in result.get('features', []):
                # the planner labels a ground footprint it was given as authored; this one is not
                if f.get('properties', {}).get('layer') == 'building_ground_footprint':
                    f['properties']['source'] = 'generated piloti variant (joint.piloti_ground_variants)'
            result['blocking'].append('generated piloti ground occupancy requires MassAgent/architect acceptance')
            if result['status']=='resolved':
                result['status']='needs_evidence'
            result['handoff'].update(input_hash=digest(request),hard_pass=False,
                status='failed' if result['status']=='needs_revision' else 'needs_evidence')
            result['piloti_strip_m']=depth
            layouts.append(result)
    shortlist=[]
    for p in (footprint_candidates(host,target,front,module,angle_deg=explicit_angle)
              if opts.get('target_surface_stalls') is not None else []):
        free = site.difference(p)
        free = free.difference(pedestrian['vehicle_blocked'])
        rows = row_candidates(site,free,p,Polygon(),road,front,rules,
                              int(opts['target_surface_stalls']),
                              int(request.get('law',{}).get('required_accessible_spaces') or 0),
                              step=2,limit=2,
                              **({'allowed_angles':[explicit_angle,explicit_angle+90],
                                  'preserve_banks':True} if explicit_angle is not None else {}))
        count = max((exclude_reserved_stalls(r,pedestrian['reserved'])['provided'] for r in rows),default=0)
        shortlist.append((count,p))
    shortlist.sort(key=lambda v:-v[0])
    for _, p in shortlist[:2]:
        candidate = copy.deepcopy(request)
        candidate['footprint'] = mapping(p)
        result = solve(candidate)
        result['blocking'].append('generated mass footprint requires MassAgent/architect acceptance')
        if result['status']=='resolved':
            result['status']='needs_evidence'
        result['handoff'].update(input_hash=digest(request),hard_pass=False,
            status='failed' if result['status']=='needs_revision' else 'needs_evidence')
        layouts.append(result)
    surface_target=opts.get('target_surface_stalls')
    def rank(r):
        from .planner_rank import drive_burden
        metrics=r['metrics']
        surface=sum(v['provided_spaces'] for v in r['levels'] if v['level']==0)
        return (r['validation']['geometry_status']=='passed',
                min(metrics['provided_accessible_stalls'],metrics['required_accessible_stalls'] or 0),
                min(metrics['provided_parking_stalls'],metrics['planned_parking_stalls'] or 0),
                -abs(surface-surface_target) if surface_target is not None else 0,
                -drive_burden(r['features'], metrics['provided_parking_stalls']))
    chosen=max(layouts,key=rank)
    chosen['joint_search']={'screened_placements':len(shortlist),'complete_layouts':len(layouts),
        'selected_index':layouts.index(chosen),'target_footprint_m2':target,
        'scope':'equal-area generated mass alternatives and piloti variants of the generated zone; authored mass remains fixed',
        'alternatives':[{'provided':r['metrics']['provided_parking_stalls'],
            'surface':sum(v['provided_spaces'] for v in r['levels'] if v['level']==0),
            'excavation_m2':r['metrics']['excavation_m2'],
            'piloti_strip_m':r.get('piloti_strip_m'),
            'geometry_status':r['validation']['geometry_status']} for r in layouts]}
    return chosen
