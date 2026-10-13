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


def _diverse_order(items, geometry):
    """Farthest-first geometry sampling, seeded by the existing order, not a quality score."""
    pending = list(items)
    if not pending:
        return []
    selected = [pending.pop(0)]
    distances = [float('inf')] * len(pending)
    while pending:
        last = geometry(selected[-1])
        distances = [min(d, geometry(item).symmetric_difference(last).area)
                     for item, d in zip(pending, distances)]
        index = max(range(len(pending)), key=lambda i: distances[i])
        selected.append(pending.pop(index))
        distances.pop(index)
    return selected


def screen_placements(proposals, evaluate, demand, *, budget=64):
    """Bound screens across positions and ground occupancies, without demand-hit pruning."""
    groups = {}
    for index, proposal in enumerate(proposals):
        groups.setdefault(proposal[0].wkb, []).append((index, proposal))
    families = _diverse_order(list(groups.values()), lambda group: group[0][1][0])
    # Share the budget between upper positions and occupancy choices on each upper.
    upper_budget = max(1, min(budget, int(2 * math.sqrt(budget))))
    families = [_diverse_order(group, lambda item: item[1][1]) for group in families[:upper_budget]]
    pending = [family[i] for i in range(max(map(len, families), default=0))
               for family in families if i < len(family)]
    evaluated = []
    for index, (p, ground, choice) in pending[:budget]:
        evaluated.append((evaluate(p, ground, choice), p, ground, choice, index))
    evaluated.sort(key=lambda v: (-v[0], -round(v[2].area, 6), v[4]))
    return [v[:4] for v in evaluated], len(proposals)-len(evaluated)


def _complete_shortlist(screened, budget):
    # Keep exploitation slots, then sample distinct upper geometry before repeating it.
    selected = list(screened[:max(1, budget // 3)])
    pending = list(screened[len(selected):])
    while pending and len(selected) < budget:
        distances = [min(item[1].symmetric_difference(other[1]).area for other in selected)
                     for item in pending]
        if max(distances) <= EPS:
            distances = [min(item[2].symmetric_difference(other[2]).area for other in selected)
                         for item in pending]
        index = max(range(len(pending)), key=lambda i: distances[i])
        selected.append(pending.pop(index))
    return selected


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
    from backend.app.modules.design.generation.maas.masterplan.placement_state import _choices
    from backend.app.modules.design.generation.maas.masterplan.entry_constraints import required_corner_clearance
    opts = request.get('options', {})
    from .planning_portfolio import policy, retain
    selection_policy, portfolio_limit = policy(opts)
    screen_budget = opts.get('max_joint_screenings', 64)
    complete_budget = opts.get('max_joint_layouts', 6)
    for name, value, maximum in [('max_joint_screenings', screen_budget, 512),
                                  ('max_joint_layouts', complete_budget, 16)]:
        if type(value) is not int or not 1 <= value <= maximum:
            raise ValueError(f'{name} must be an integer in 1..{maximum}')
    explicit_angle = layout_axis_angle(request)
    baseline = solve(copy.deepcopy(request))
    if baseline.get('planner_invoked') is False:
        return baseline
    placement_stage = opts.get('planning_stage') == 'placement'
    if (request.get('footprint') or request.get('ground_footprint') or request.get('core')
            or request.get('columns') or request.get('building_entrance')
            or opts.get('joint_placement_search') is False
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
    prohibited = shape(request['vehicle_prohibited']) if request.get('vehicle_prohibited') else None
    entry_clearance = required_corner_clearance(opts)
    straight_entry = opts.get('entry_alignment') == 'straight'
    screen_angle = explicit_angle
    if placement_stage and screen_angle is None:
        from .layout_axis import planning_axis_angle
        screen_angle = planning_axis_angle(request)
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
    proposals=[]
    screen_demand = opts.get('target_surface_stalls')
    demand_source = 'explicit_surface_target'
    if screen_demand is None and placement_stage:
        screen_demand = baseline['metrics'].get('planned_parking_stalls')
        demand_source = 'planned_parking_demand_search_bound'
        if screen_demand is not None and opts.get('max_surface_stalls') is not None:
            screen_demand = min(screen_demand, opts['max_surface_stalls'])
    screen_demand = int(screen_demand or 0)
    for p in (footprint_candidates(host,target,front,module,angle_deg=screen_angle)
              if surface_possible and screen_demand > 0 else []):
        variants = [(p, None)]
        if placement_stage and surface_possible:
            variants += [(shape(choice['ground']), choice) for choice in _choices(p, rules)]
        for ground, choice in variants:
            proposals.append((p, ground, choice))
    def screen(p, ground, choice):
        free = site.difference(ground).difference(pedestrian['vehicle_blocked'])
        rows = row_candidates(site,free,p,Polygon(),road,front,rules,
                                  screen_demand,
                                  int(request.get('law',{}).get('required_accessible_spaces') or 0),
                                  step=1 if placement_stage else 2,limit=2,occupied_footprint=ground,
                                  prohibited=prohibited,entry_clearance_m=entry_clearance,
                                  straight_entry=straight_entry,
                                  turn_radius_m=(opts.get('vehicle') or {}).get('turning_radius_outer_m'),
                                  turn_lane_m=opts.get('turn_lane_m'),field=opts.get('parking_field', 'auto'),
                                  **({'allowed_angles':[screen_angle] if straight_entry else [screen_angle,screen_angle+90],
                                      'preserve_banks':True} if screen_angle is not None else {}))
        return max((exclude_reserved_stalls(r,pedestrian['reserved'])['provided'] for r in rows),default=0)
    shortlist, skipped = screen_placements(proposals, screen, screen_demand, budget=screen_budget)
    # Preserve enclosed ground when surface counts tie; this limits programme
    # loss in the shortlist and is not an architectural quality score.
    shortlist.sort(key=lambda v:(-v[0], -round(v[2].area, 6)))
    selected_proposals = _complete_shortlist(shortlist, complete_budget)
    for _, p, ground, choice in selected_proposals:
        candidate = copy.deepcopy(request)
        candidate['footprint'] = mapping(p)
        if choice is not None:
            candidate['ground_footprint'] = mapping(ground)
        result = solve(candidate)
        result['blocking'].append('generated mass footprint requires MassAgent/architect acceptance')
        if choice is not None:
            for f in result.get('features', []):
                if f.get('properties', {}).get('layer') == 'building_ground_footprint':
                    f['properties']['source'] = 'generated piloti variant (placement_state._choices)'
            result['blocking'].append('generated piloti ground occupancy requires MassAgent/architect acceptance')
            result['piloti_strip_m'] = choice['depth_m']
            result['piloti_choice_id'] = choice['id']
        if result['status']=='resolved':
            result['status']='needs_evidence'
        result['handoff'].update(input_hash=digest(request),hard_pass=False,
            status='failed' if result['status']=='needs_revision' else 'needs_evidence')
        layouts.append(result)
    surface_target=opts.get('target_surface_stalls')
    def rank(r):
        from .planner_rank import drive_burden
        from shapely.ops import unary_union
        metrics=r['metrics']
        surface=sum(v['provided_spaces'] for v in r['levels'] if v['level']==0)
        ground = [shape(f['geometry']) for f in r['features']
                  if f.get('properties', {}).get('layer') == 'building_ground_footprint'
                  and f.get('properties', {}).get('level', 0) == 0]
        if not ground:
            ground = [shape(f['geometry']) for f in r['features']
                      if f.get('properties', {}).get('layer') == 'building_footprint']
        return (r['validation']['geometry_status']=='passed',
                min(metrics['provided_accessible_stalls'],metrics['required_accessible_stalls'] or 0),
                min(metrics['provided_parking_stalls'],metrics['planned_parking_stalls'] or 0),
                -abs(surface-surface_target) if surface_target is not None else 0,
                round(unary_union(ground).area, 6),
                -drive_burden(r['features'], metrics['provided_parking_stalls']))
    chosen=max(layouts,key=rank)
    portfolio = retain(layouts, chosen, limit=portfolio_limit) if selection_policy=='siting_portfolio_v1' else None
    chosen['joint_search']={'screened_placements':len(shortlist),'complete_layouts':len(layouts),
        'screen_demand':screen_demand, 'screen_demand_source':demand_source,
        'proposed_placements':len(proposals),'screens_pruned_by_upper_bound':0,
        'screens_skipped_by_budget':skipped, 'max_joint_screenings':screen_budget,
        'max_joint_layouts':complete_budget, 'complete_proposals':len(selected_proposals),
        'screened_upper_footprints':len({v[1].wkb for v in shortlist}),
        'solved_upper_footprints':len({v[1].wkb for v in selected_proposals}),
        'selection_scope':'bounded geometry sampling, not architectural quality or exhaustive feasibility',
        'selected_index':layouts.index(chosen),'target_footprint_m2':target,
        'scope':'equal-area generated mass alternatives and owner piloti choices; authored mass remains fixed',
        'screen_tie_break':'preserve enclosed ground area among equal surface counts; not architectural quality',
        'final_tie_break':'preserve enclosed ground area before drive burden at equal feasibility and parking attainment',
        'alternatives':[{'provided':r['metrics']['provided_parking_stalls'],
            'surface':sum(v['provided_spaces'] for v in r['levels'] if v['level']==0),
            'excavation_m2':r['metrics']['excavation_m2'],
            'piloti_strip_m':r.get('piloti_strip_m'),
            'geometry_status':r['validation']['geometry_status']} for r in layouts]}
    if portfolio is not None:
        chosen['planning_portfolio'] = {k:v for k,v in portfolio.items() if k!='candidates'}
        chosen['planning_candidates'] = portfolio['candidates']
    return chosen
