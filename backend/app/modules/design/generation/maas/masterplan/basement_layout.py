"""Compare actual programme bands and connected parking on a basement slab."""
import math
from shapely.affinity import rotate
from shapely.geometry import LineString, Polygon, box
from backend.app.modules.design.generation.maas.masterplan.geometry import EPS, parts, union_or_empty
from backend.app.modules.design.generation.maas.masterplan.program import plant_zone_candidates, split_plant_zone_candidates, block_plant_zone_candidates
from backend.app.modules.design.generation.maas.masterplan.rows import row_candidates
from backend.app.modules.design.generation.maas.masterplan.bounded_packing import pack_level
from backend.app.modules.design.generation.maas.masterplan.circulation import closed_aisle_loop


def module_plates(envelope, mandatory, module_depth, aisle_width, angle_deg, *, target_area=None,
                  required=None, stall_width=None, max_modules=4, limit=4):
    """Plates cut to whole parking modules, aligned to the parking angle.

    A slab grown outwards as a buffer hull can close an aisle loop only if it happens to come out
    deep enough. A closed loop needs two stall bands and a cross aisle at each end, so the depth must
    be at least two modules (2 x (stall + aisle + stall) = 32 m with 2.5/5.0/6.0 m rules) plus the
    cross aisles; cutting the plate to n whole modules makes that true BY CONSTRUCTION instead of by
    luck. This is the proportioning rule practice works to - CCDC controls the overall width of a
    parking structure as a multiple of the bay width, and Xu Han-zhe et al., J. BUPT 42(4):102-108
    (2019) plan the perimeter ring first and decompose the interior afterwards.

    Returns plates inside `envelope` that still cover `mandatory` (the ramp and obstacles), n modules
    deep across the bands, at the three depth positions that matter - flush with each end of the
    mandatory and centred on it - and, when a `target_area` is given, cut to the width that meets it
    so the dig stays demand-sized instead of taking the whole envelope.
    """
    if envelope.is_empty or module_depth <= 0:
        return []
    rot = lambda g, a: rotate(g, a, origin=(0, 0))  # noqa: E731
    env = rot(envelope, -angle_deg)
    must = rot(mandatory, -angle_deg) if mandatory is not None and not mandatory.is_empty else None
    ex0, ey0, ex1, ey1 = env.bounds
    mx0, my0, mx1, my1 = must.bounds if must is not None else (ex0, ey0, ex1, ey1)
    out = []
    for n in range(2, max_modules + 1):
        depth = n * module_depth + 2 * aisle_width   # n bands plus a cross aisle at each end
        if depth > (ey1 - ey0) + EPS:
            break
        widths = [ex1 - ex0]
        if target_area:
            # the tighter plate: only as wide as the demand needs at this depth
            widths.insert(0, min(max(target_area / depth, mx1 - mx0), ex1 - ex0))
        if required and stall_width:
            # WIDTH FROM THE CARS, NOT FROM AN AREA BUDGET. n modules carry 2n rows of stalls, so a
            # plate `depth` deep needs width = required * stall_width / (2n) to hold the whole demand
            # on ONE level - plus the two cross aisles the loop's return leg costs, plus whatever the
            # ramp displaces. Sized by area instead, the plate came out 44.0 x 33.8 = 1,487 m2: four
            # rows of 13.5 bays is 54 cars of the 62 required, so an eighth-full second level had to
            # be dug and the ranking - which hates a thin level, correctly - threw the whole
            # proportioned plate away. Derived this way the same demand asks for 44.0 x 39.4, one
            # level, and the loop comes with it.
            rows_per_plate = 2 * n
            needed = float(required) * float(stall_width) / rows_per_plate + 2 * aisle_width
            widths.insert(0, min(max(needed, mx1 - mx0), ex1 - ex0))
        for width in dict.fromkeys(round(w, 3) for w in widths):
            for x0 in dict.fromkeys([mx0, mx1 - width, (mx0 + mx1) / 2 - width / 2]):
                x0 = min(max(x0, ex0), ex1 - width)
                for y0 in dict.fromkeys([my1 - depth, my0, (my0 + my1) / 2 - depth / 2]):
                    y0 = min(max(y0, ey0), ey1 - depth)
                    plate = box(x0, y0, x0 + width, y0 + depth).intersection(env)
                    plate = next((q for q in sorted(parts(plate), key=lambda q: -q.area)
                                  if must is None or q.buffer(EPS).covers(must)), None)
                    if plate is None or plate.is_empty:
                        continue
                    plate = rot(plate, angle_deg)
                    if not any(plate.symmetric_difference(previous).area < .01 for previous in out):
                        out.append(plate)
                        if len(out) >= limit:
                            return out
    return out


def slab_envelopes(seed, envelope, mandatory, target_area, module_depth, *, aisle_width=None, angle_deg=0.0,
                   required=None, stall_width=None):
    """Demand-sized geometric alternatives within an authorized underground host.

    Growth is a search dimension, not a claim that an area budget proves fit.
    Every returned slab still needs programme, parking and circulation solving.
    """
    if not envelope.buffer(EPS).covers(mandatory):
        return []
    seed=seed.union(mandatory).convex_hull
    def grow(distance):
        clipped=seed.buffer(distance,join_style=2).intersection(envelope) if distance else seed.intersection(envelope)
        return next((p for p in sorted(parts(clipped),key=lambda p:-p.area)
                     if p.buffer(EPS).covers(mandatory)),None)
    x0,y0,x1,y1=envelope.bounds
    lo,hi=0,math.hypot(x1-x0,y1-y0)
    for _ in range(32):
        mid=(lo+hi)/2
        p=grow(mid)
        if p is None or p.area<target_area:
            lo=mid
        else:
            hi=mid
    # Programme topology can become feasible between the area-budget slab and
    # a half-module expansion. That expansion may add hundreds of square
    # metres on a long perimeter. Refine its area interval once, retaining
    # the original candidates and a strict five-candidate upper bound.
    expanded_distance=hi+module_depth/2
    budget_slab, expanded_slab=grow(hi),grow(expanded_distance)
    mid_distance=hi
    if budget_slab is not None and expanded_slab is not None:
        midpoint_area=(budget_slab.area+expanded_slab.area)/2
        lower,upper=hi,expanded_distance
        for _ in range(24):
            mid_distance=(lower+upper)/2
            probe=grow(mid_distance)
            if probe is None or probe.area<midpoint_area:
                lower=mid_distance
            else:
                upper=mid_distance
        mid_distance=upper
    out=[]
    full_host=next((p for p in sorted(parts(envelope),key=lambda p:-p.area)
                    if p.buffer(EPS).covers(mandatory)),None)
    # Module-proportioned plates first: a buffer hull is deep enough for a closed loop only by luck,
    # and when it is not, the whole envelope wins the ranking and the dig pays for it. These are cut
    # to whole modules along the bands, so two bands and their cross aisles fit by construction.
    proportioned=(module_plates(envelope,mandatory,module_depth,float(aisle_width),angle_deg,
                                target_area=target_area,required=required,stall_width=stall_width,
                                limit=4) if aisle_width else [])
    # THE BUILDING PLATE WAS NEVER A CANDIDATE. Every slab here grows from the ramp landing (branch
    # one) or from the surface rows (branch two), so the search could not propose the arrangement
    # practice uses: ALT1-006 shows the basement outline following the building's, with only the
    # curved ramp crossing the yard. Excavation under the plate is largely paid for by the
    # foundation; excavation beside it is not. The candidate must still cover the ramp landing and
    # still solve programme, packing and circulation like any other - it is an option, not a rule.
    # Reserve the final slot for the full authorized host. This retains both
    # search extremes under the six-solve budget, without claiming optimality.
    budget = 5 if full_host is not None else 6
    for p in (*proportioned,grow(0),grow(hi),grow(mid_distance),grow(expanded_distance)):
        if full_host is not None and p is not None and p.symmetric_difference(full_host).area < .01:
            continue
        if p is not None and not any(p.symmetric_difference(previous).area<.01 for previous in out):
            out.append(p)
            # Every slab returned here is a full basement solve upstream - programme, packing and
            # circulation on two levels - so the list is a search budget, not a catalogue. The
            # proportioned plates come first and the full host is reached last, which keeps both ends
            # of the range: the tightest dig that can hold the demand, and the undug-to-the-boundary
            # option that was the only behaviour before any of this existed.
            if len(out)>=budget:
                break
    if full_host is not None:
        out.append(full_host)
    return out


def solve_basement_level(slab, ramp, obstacles, rooms, rules, required, accessible,
                         *, angle=0, expanded_needed=None, turn_radius_m=None,
                         turn_lane_m=None, field='auto', departure_landing=None, require_full_width=False,
                         orthogonal_layout=False, module_family=None, module_axis='both'):
    if module_axis not in ('both', 'along_axis', 'cross_axis'):
        raise ValueError('unsupported module axis')
    landing=ramp['lower_landing']
    landings=union_or_empty([landing,departure_landing] if departure_landing is not None else [landing])
    keep_clear=union_or_empty([obstacles,ramp['polygon']])
    zones=plant_zone_candidates(slab,rooms,keep_clear=keep_clear,angle_deg=angle) if rooms and not orthogonal_layout else ([] if rooms else [None])
    if rooms:
        zones+=block_plant_zone_candidates(slab,rooms,keep_clear=keep_clear,angle_deg=angle,
                                          grid_steps=8 if orthogonal_layout else 2)
    if rooms and len(rooms)>1 and not orthogonal_layout:
        zones+=split_plant_zone_candidates(slab,rooms,keep_clear=keep_clear,angle_deg=angle,limit=4)
    if not zones:
        return None
    results=[]
    def rank(p, zone):
        return (min(p['accessible'],accessible),min(p['provided'],required),
            min(sum(s['type']=='expanded' for s in p['stalls']),expanded_needed or 0),
            p.get('score', 0),-p['drive'].area)
    for zone in zones:
        blocked=union_or_empty([obstacles,ramp['polygon'].difference(landings),
                                zone['zone'] if zone else Polygon()])
        free=slab.difference(blocked)
        # the landing is the packer's road-equivalent; take its largest piece if it was clipped apart
        landing_edge=max(parts(landing),key=lambda g:g.area,default=landing)
        if module_family is not None:
            from .parking_modules import module_candidates
            module_angles=([angle,angle+90] if module_axis=='both' else
                           [angle+90] if module_axis=='cross_axis' else [angle])
            plans=module_candidates(free,[landing]+([departure_landing] if departure_landing is not None else []),
                rules,required,accessible,family=module_family,angles=module_angles,
                field=field,expanded_needed=expanded_needed)
        else:
            plans=row_candidates(slab,free,Polygon(),obstacles,LineString(landing_edge.exterior.coords),
                None,rules,required,accessible,expanded_needed=expanded_needed,
                turn_radius_m=turn_radius_m,turn_lane_m=turn_lane_m,field=field,
                allowed_angles=[angle, angle+90] if orthogonal_layout else None,
                preserve_banks=orthogonal_layout)
        def clean(plan):
            # UNION THE VALID FORMS, NOT THE RAW ONES. GEOS raises "unable to assign free hole to a
            # shell" when an operand carries a hole its shell no longer contains, which the packer
            # can produce on an irregular slab - a plate-shaped basement hugging the building is the
            # first thing to reach it. Repairing each operand first is the standard remedy and costs
            # nothing on already-valid input.
            drive=union_or_empty([plan['drive'].buffer(0),landings.buffer(0)]).buffer(0)
            if departure_landing is not None:
                width=float(rules['aisle_width_m'])
                corridors=[Polygon()] if drive.geom_type=='Polygon' else []
                a,b=landing.centroid,departure_landing.centroid
                heading=math.degrees(math.atan2(b.y-a.y,b.x-a.x))
                for orientation in set((0,heading)):
                    aa,bb=rotate(a,-orientation,origin=(0,0)),rotate(b,-orientation,origin=(0,0))
                    x0,y0,x1,y1=rotate(ramp['polygon'],-orientation,origin=(0,0)).bounds
                    paths=[[(aa.x,aa.y),(bb.x,bb.y)]]
                    paths += [[(aa.x,aa.y),(x,aa.y),(x,bb.y),(bb.x,bb.y)] for x in (x0-width/2,x1+width/2)]
                    paths += [[(aa.x,aa.y),(aa.x,y),(bb.x,y),(bb.x,bb.y)] for y in (y0-width/2,y1+width/2)]
                    corridors += [rotate(LineString(path).buffer(width/2,cap_style=2,join_style=2),
                        orientation,origin=(0,0)) for path in paths]
                connected=[]
                for corridor in corridors:
                    combined=drive.union(corridor).buffer(0)
                    if combined.geom_type=='Polygon' and free.buffer(EPS).covers(combined):
                        retained=[s for s in plan['stalls'] if s['polygon'].intersection(combined).area<=EPS]
                        connected.append((len(retained),-combined.area,combined))
                if not connected:
                    return None
                drive=max(connected,key=lambda c:c[:2])[2]
            stalls=[s for s in plan['stalls'] if s['polygon'].intersection(landings).area<=EPS
                    and s['polygon'].intersection(drive).area<=EPS]
            if field=='ring' and closed_aisle_loop(drive,rules.get('aisle_width_m')) is None:
                return None
            if require_full_width:
                from backend.app.modules.design.generation.maas.masterplan.circulation import full_width_stall_access
                if not full_width_stall_access(drive, [s['polygon'] for s in stalls],
                                                [landing], rules['aisle_width_m']):
                    return None
            return {**plan,'stalls':stalls,'provided':len(stalls),'drive':drive,
                    'accessible':sum(s['type']=='accessible' for s in stalls),
                    'search_count':plan.get('search_count',1)}
        plans=[p for p in (clean(p) for p in plans) if p is not None]
        if (field=='ring' or module_family is not None) and not plans:
            continue
        if not plans and departure_landing is not None:
            empty=clean({'stalls':[],'drive':Polygon(),'provided':0,'accessible':0})
            if empty is not None:
                plans.append(empty)
            else:
                continue
        best=max(plans,key=lambda p:rank(p,zone)) if plans else {
            'stalls':[],'drive':landing,'provided':0,'accessible':0,'search_count':0}
        best={**best,'generation':{'requested_field':field,
            'selected_engine':('parking_modules' if module_family is not None else 'row_candidates') if plans else 'empty_landing',
            'selected_pattern':best.get('pattern'),'fallback_used':False,
            **({'module_layout':best['module_layout']} if best.get('module_layout') else {})}}
        results.append({'zone':zone,'parking':best,'free':free})
    # Spend expensive spine-search effort on a bounded beam after comparing
    # programme/row alternatives; avoid multiplying full searches at every edge.
    results.sort(key=lambda item:rank(item['parking'],item['zone']),reverse=True)
    for item in (results[:2] if field!='ring' and module_family is None else []):
        best,zone=item['parking'],item['zone']
        if (best['provided']<required or best['accessible']<accessible
                or sum(s['type']=='expanded' for s in best['stalls'])<(expanded_needed or 0)):
            # clean closes over the final zone's free host; restore this host
            # before checking the separately ranked programme alternative.
            free=item['free']
            generic=clean(pack_level(free,[landing],rules,required,accessible,preferred_angle=angle,
                                     require_full_width=require_full_width,
                                     allowed_angles=[angle,angle+90] if orthogonal_layout else None,
                                     preserve_banks=orthogonal_layout))
            if generic is not None and rank(generic,zone)>rank(best,zone):
                item['parking']={**generic,'generation':{'requested_field':field,
                    'selected_engine':'generic_packer','selected_pattern':generic.get('pattern'),
                    'fallback_used':True}}
    for item in results:
        item.pop('free')
    return max(results,key=lambda item:rank(item['parking'],item['zone'])) if results else None
