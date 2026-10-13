"""Source-scoped tandem alternatives with independently checked front/rear geometry."""
from copy import deepcopy
import math
from shapely.affinity import translate
from shapely.geometry import LineString, Polygon, mapping, shape
from shapely.ops import unary_union
from .geometry import EPS


def _scope(request, count):
    owner = (request.get('rules') or {}).get('owner_snapshot') or {}
    rule = (owner.get('conditional_options') or {}).get('tandem') or {}
    return (owner.get('status') == 'rules_available' and count > 0
            and count <= rule.get('max_total_spaces',0) and rule.get('max_depth_spaces',0) >= 2)


def _rear(front, drive):
    rect = front.minimum_rotated_rectangle
    if rect.symmetric_difference(front).area > EPS:
        return None
    coords = list(rect.exterior.coords)
    edges = [LineString([a,b]) for a,b in zip(coords,coords[1:])]
    width = min(edge.length for edge in edges)
    for edge in edges:
        if abs(edge.length-width) > EPS or edge.intersection(drive.buffer(EPS)).length < width-EPS:
            continue
        mid, center = edge.interpolate(.5,normalized=True), front.centroid
        return translate(front, xoff=2*(center.x-mid.x), yoff=2*(center.y-mid.y))
    return None


def certified_rears(request, features):
    stalls = [f for f in features if f.get('properties',{}).get('layer') == 'parking_stall']
    ids = [f['properties'].get('stall_id') for f in stalls]
    indexed = dict(zip(ids, stalls))
    claimed = [f['properties'].get('tandem_front_id') for f in stalls if f['properties'].get('tandem_front_id')]
    if not claimed:
        return set(), []
    drive = unary_union([shape(f['geometry']) for f in features if f.get('geometry') and f.get('properties',{}).get('layer') in ('parking_aisle','vehicular_access') and f['properties'].get('level',0)==0])
    certified, checks = set(), []
    for rear in stalls:
        props = rear['properties']
        fid = props.get('tandem_front_id')
        if not fid:
            continue
        front = indexed.get(fid)
        ok = bool(_scope(request,len(stalls)) and len(ids)==len(set(ids)) and claimed.count(fid)==1 and front
            and props.get('level',0)==front['properties'].get('level',0)==0
            and props.get('type')==front['properties'].get('type')=='standard_90deg'
            and not front['properties'].get('tandem_front_id') and front.get('geometry') and rear.get('geometry'))
        expected = _rear(shape(front['geometry']),drive) if ok else None
        ok = bool(ok and expected is not None and expected.symmetric_difference(shape(rear['geometry'])).area <= EPS)
        checks.append({'id':f"tandem_pair:{props.get('stall_id')}", 'status':'passed' if ok else 'failed',
                       'front_stall_id':fid, 'rear_stall_id':props.get('stall_id'),
                       'independent_exit':False, 'scope':'two bays in depth; front vehicle must move for rear exit'})
        if ok:
            certified.add(props['stall_id'])
    return certified, checks


def expand(request, candidate, target):
    if target is None or not _scope(request,target) or candidate.get('provided',0) >= target:
        return None
    options = request.get('options') or {}
    for key in ('max_surface_stalls','target_surface_stalls'):
        if options.get(key) is not None:
            target = min(target, options[key])
    if candidate.get('provided',0) >= target:
        return None
    features = candidate.get('features') or []
    stalls = [f for f in features if f.get('properties',{}).get('layer')=='parking_stall']
    if not stalls:
        seeded = _seed(request, candidate, target)
        return expand(request, seeded, target) if seeded else None
    if any(f['properties'].get('level',0)!=0 for f in stalls):
        return None
    drive = unary_union([shape(f['geometry']) for f in features if f.get('properties',{}).get('layer') in ('parking_aisle','vehicular_access')])
    ground_layer = 'building_ground_footprint' if any(f.get('properties',{}).get('layer')=='building_ground_footprint' for f in features) else 'building_footprint'
    blocked = unary_union([shape(f['geometry']) for f in features if f.get('properties',{}).get('layer') in
        ('parking_stall','parking_aisle','vehicular_access','ramp','column','building_core',ground_layer)] +
        [shape(request[k]) for k in ('pedestrian_reserved_area',) if request.get(k)])
    site = shape(request['site'])
    additions = []
    for front in stalls:
        props = front['properties']
        if props.get('type')!='standard_90deg' or props.get('tandem_front_id') or not props.get('stall_id'):
            continue
        rear = _rear(shape(front['geometry']), drive)
        if rear is None or not site.buffer(EPS).covers(rear) or rear.intersection(blocked).area > EPS:
            continue
        additions.append({'type':'Feature','geometry':mapping(rear),'properties':{
            **props,'stall_id':props['stall_id']+'-rear','tandem_front_id':props['stall_id'],
            'independent_exit':False}})
        blocked = blocked.union(rear)
        if len(stalls)+len(additions) >= target:
            break
    if not additions:
        return None
    result = deepcopy(candidate)
    result['features'].extend(additions)
    result['provided'] = len(stalls)+len(additions)
    for level in result.get('levels',[]):
        if level.get('level')==0:
            level['provided_spaces'] = result['provided']
    result['pattern'] = 'tandem'
    result['tandem_added'] = len(additions)
    return result


def _seed(request, candidate, target):
    """A front bay for deep narrow pockets omitted by the ordinary row packer."""
    rules = request.get('rules') or {}
    if target < 2 or not request.get('frontage') or not all(rules.get(k) for k in ('stall_width_m','stall_length_m','aisle_width_m')):
        return None
    width, length, aisle = (float(rules[k]) for k in ('stall_width_m','stall_length_m','aisle_width_m'))
    features = candidate.get('features') or []
    ground_layer = 'building_ground_footprint' if any(f.get('properties',{}).get('layer')=='building_ground_footprint' for f in features) else 'building_footprint'
    obstacles = [shape(f['geometry']) for f in features
                 if f.get('geometry') and f.get('properties',{}).get('layer') in
                 (ground_layer,'building_core','column','ramp')]
    if request.get('pedestrian_reserved_area'):
        obstacles.append(shape(request['pedestrian_reserved_area']))
    blocked = unary_union(obstacles)
    free = shape(request['site']).difference(blocked)
    road = shape(request['frontage'])
    for line in getattr(road,'geoms',[road]):
        if line.geom_type != 'LineString':
            continue
        coords = list(line.coords)
        for a,b in zip(coords,coords[1:]):
            run = math.dist(a,b)
            if run < aisle:
                continue
            ux,uy = (b[0]-a[0])/run,(b[1]-a[1])/run
            for sign in (-1,1):
                nx,ny = -uy*sign,ux*sign
                def cell(start,depth,w,h):
                    x,y = a[0]+ux*start+nx*depth,a[1]+uy*start+ny*depth
                    return Polygon([(x,y),(x+ux*w,y+uy*w),(x+ux*w+nx*h,y+uy*w+ny*h),(x+nx*h,y+ny*h)])
                drive = cell(0,0,run,aisle)
                if not free.buffer(EPS).covers(drive):
                    continue
                for i in range(int(run/width)):
                    bay = cell(i*width,aisle,width,length)
                    rear = cell(i*width,aisle+length,width,length)
                    if not free.buffer(EPS).covers(bay.union(rear)):
                        continue
                    out = deepcopy(candidate)
                    out['features'].extend([
                        {'type':'Feature','geometry':mapping(drive),'properties':{'layer':'parking_aisle','level':0,'width_m':aisle,'role':'surface_entry_connector'}},
                        {'type':'Feature','geometry':mapping(bay),'properties':{'layer':'parking_stall','level':0,'stall_id':'G-T001','type':'standard_90deg','width_m':width,'length_m':length}}])
                    out['provided'] = 1
                    return out
    return None
