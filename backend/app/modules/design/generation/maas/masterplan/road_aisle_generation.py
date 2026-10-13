"""Optional surface rows using the source-owned road strip and Law-scoped width."""
from copy import deepcopy
import math
from shapely.geometry import LineString, Polygon, shape
from .geometry import EPS, feature, union_or_empty, parts, digest


def generate(request, base, target):
    if not request.get('road_aisle_context') or not target:
        return []
    from .road_aisle import scope
    options = request.get('options') or {}
    if options.get('parking_strategy', 'auto') not in ('auto', 'surface', 'ground_surface', 'mixed'):
        return []
    bound = scope(request)
    if bound.get('status') != 'ready':
        return []
    if (bound['law'].get('input_identity') or {}).get('parking_angle') != 'perpendicular':
        return []
    rules = request.get('rules') or {}
    width, length = rules.get('stall_width_m'), rules.get('stall_length_m')
    if any(isinstance(v, bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v <= 0 for v in (width,length)):
        return []
    # Accessible bays need their own circulation and access specification; this
    # family never silently substitutes standard bays for that obligation.
    if (request.get('law') or {}).get('required_accessible_spaces', 0):
        return []
    target = min(int(target), bound['max_total_spaces'])
    for key in ('max_surface_stalls', 'target_surface_stalls'):
        if options.get(key) is not None:
            target = min(target,int(options[key]))
    if target <= 0:
        return []
    site = shape(request['site'])
    blocked = union_or_empty([shape(f['geometry']) for f in base if f.get('properties',{}).get('layer') in
        ('building_footprint','building_ground_footprint','building_core','column','pedestrian_reserved_area','pedestrian_route')]
        + [shape(request[k]) for k in ('pedestrian_reserved_area',) if request.get(k)])
    prohibited = shape(request['vehicle_prohibited']) if request.get('vehicle_prohibited') else None
    frontage, included, required = bound['frontage'], bound['included'], bound['required_width_m']
    lines = [frontage] if frontage.geom_type == 'LineString' else list(frontage.geoms)
    included_tolerance = included.buffer(EPS)
    result, seen = [], set()
    for line in lines:
        for a,b in zip(line.coords,list(line.coords)[1:]):
            segment = LineString([a,b])
            span = segment.length
            if span < width:
                continue
            tx,ty = (b[0]-a[0])/span, (b[1]-a[1])/span
            for sign in (1,-1):
                nx,ny = -ty*sign,tx*sign
                def rectangle(start, end, near, far):
                    return Polygon([(a[0]+tx*x+nx*y,a[1]+ty*x+ny*y)
                                    for x,y in ((start,near),(end,near),(end,far),(start,far))])
                depth_limit = min(required,max((-(x-a[0])*nx-(y-a[1])*ny
                    for poly in parts(included) for x,y in poly.exterior.coords),default=0))
                if depth_limit <= EPS:
                    continue
                for count in range(min(target,int((span+EPS)//width)),0,-1):
                    occupied = count*width
                    for start in sorted(set((0.0,(span-occupied)/2,span-occupied))):
                        end = start+occupied
                        contact = LineString([(a[0]+tx*start,a[1]+ty*start),(a[0]+tx*end,a[1]+ty*end)])
                        if prohibited is not None and contact.intersection(prohibited.buffer(EPS)).length > EPS:
                            continue
                        lo,hi = 0.0,depth_limit
                        if included_tolerance.covers(rectangle(start,end,-hi,0)):
                            lo = hi
                        else:
                            # Bounded numerical search for a fully covered strip,
                            # never a width inferred from a centreline buffer.
                            for _ in range(48):
                                mid = (lo+hi)/2
                                if included_tolerance.covers(rectangle(start,end,-mid,0)):
                                    lo = mid
                                else:
                                    hi = mid
                        depth = lo
                        if depth <= EPS:
                            continue
                        deficit = max(0,required-depth)
                        external = rectangle(start,end,-depth,0)
                        internal = rectangle(start,end,0,deficit) if deficit > EPS else Polygon()
                        stalls = [rectangle(start+i*width,start+(i+1)*width,deficit,deficit+length) for i in range(count)]
                        occupied_site = union_or_empty([internal,*stalls])
                        if (not site.buffer(EPS).covers(occupied_site) or occupied_site.intersection(blocked).area > EPS
                                or external.intersection(site).area > EPS):
                            continue
                        feats = deepcopy(base)
                        feats += [feature('parking_stall',stall,stall_id=f'G-RA{i+1:03d}',type='standard_90deg',
                            width_m=width,length_m=length,z_m=0,access_kind='road_aisle') for i,stall in enumerate(stalls)]
                        if not internal.is_empty:
                            feats.append(feature('parking_aisle',internal,width_m=deficit,z_m=0,access_kind='road_aisle'))
                        feats.append(feature('external_road_aisle',external,width_m=depth,z_m=0,access_kind='road_aisle'))
                        identity = digest(feats)
                        if identity in seen:
                            continue
                        seen.add(identity)
                        result.append({'strategy':'ground_surface','pattern':'road_as_aisle','features':feats,
                            'levels':[{'level':0,'z_m':0,'provided_spaces':count}], 'provided':count,
                            'accessible':0,'search_count':1,
                            'pending_reviews':['road-as-aisle source facts and authority acceptance require project review']})
    return result
