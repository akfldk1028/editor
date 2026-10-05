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


def footprint_candidates(buildable, target, front, module_depth, limit=32, *, angle_deg=None):
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


def select_joint_layout(request, solve):
    """Screen equal-area proposals, then compare complete ground/basement plans.

    A coarse surface screen is only a shortlist, never the feasibility verdict.
    The original proposal remains in the final competition. Fixed authored mass,
    core and partial-piloti input are never silently relocated by this search.
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
    if (request.get('footprint') or request.get('ground_footprint') or request.get('core')
            or request.get('columns') or opts.get('target_surface_stalls') is None
            or opts.get('joint_placement_search') is False):
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
    shortlist=[]
    for p in footprint_candidates(host,target,front,module,angle_deg=explicit_angle):
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
    layouts=[baseline]
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
    def rank(r):
        metrics=r['metrics']
        surface=sum(v['provided_spaces'] for v in r['levels'] if v['level']==0)
        return (r['validation']['geometry_status']=='passed',
                min(metrics['provided_accessible_stalls'],metrics['required_accessible_stalls'] or 0),
                min(metrics['provided_parking_stalls'],metrics['planned_parking_stalls'] or 0),
                -abs(surface-opts['target_surface_stalls']),
                -metrics['excavation_m2'])
    chosen=max(layouts,key=rank)
    chosen['joint_search']={'screened_placements':len(shortlist),'complete_layouts':len(layouts),
        'selected_index':layouts.index(chosen),'target_footprint_m2':target,
        'scope':'equal-area generated mass alternatives; authored mass remains fixed',
        'alternatives':[{'provided':r['metrics']['provided_parking_stalls'],
            'surface':sum(v['provided_spaces'] for v in r['levels'] if v['level']==0),
            'excavation_m2':r['metrics']['excavation_m2'],
            'geometry_status':r['validation']['geometry_status']} for r in layouts]}
    return chosen
