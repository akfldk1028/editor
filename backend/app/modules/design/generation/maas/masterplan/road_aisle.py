"""Source-bound exterior drive geometry; legal applicability stays with Law."""
import math
from datetime import date
from shapely.affinity import translate
from shapely.geometry import LineString, Polygon, shape
from shapely.ops import split, transform, unary_union

from .geometry import EPS, digest, polygon, parts


def _centreline_bounds_frontage(road, frontage, centreline):
    fronts = getattr(frontage, 'geoms', [frontage])
    cuts = getattr(centreline, 'geoms', [centreline])
    for front in fronts:
        points = list(front.simplify(EPS).coords)
        for a,b in zip(points,points[1:]):
            span = math.dist(a,b)
            tx,ty = (b[0]-a[0])/span,(b[1]-a[1])/span
            nx,ny = -ty,tx
            bounded = False
            for cut in cuts:
                coords = list(cut.simplify(EPS).coords)
                for c,d in zip(coords,coords[1:]):
                    offsets = [((v[0]-a[0])*tx+(v[1]-a[1])*ty,
                                (v[0]-a[0])*nx+(v[1]-a[1])*ny) for v in (c,d)]
                    along = sorted(v[0] for v in offsets)
                    depth = offsets[0][1]
                    if (along[0]>EPS or along[1]<span-EPS or abs(depth)<=EPS
                            or abs(depth-offsets[1][1])>EPS):
                        continue
                    corridor=Polygon([a,b,(b[0]+nx*depth,b[1]+ny*depth),(a[0]+nx*depth,a[1]+ny*depth)])
                    if road.buffer(EPS).covers(corridor):
                        bounded=True
                        break
                if bounded:
                    break
            if not bounded:
                return False
    return True


def scope(request):
    try:
        return _scope(request)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        return {'status': 'needs_evidence', 'reason': str(exc)}


def _scope(request):
    from pyproj import CRS, Transformer
    from backend.app.modules.law.reference.road_aisle import evaluate
    context = request.get('road_aisle_context') or {}
    receipt = (request.get('evidence') or {}).get('road_aisle_law') or {}
    source = context.get('source_context')
    if not isinstance(source, dict) or context.get('pnu') != request.get('pnu') or source.get('pnu') != request.get('pnu'):
        raise ValueError('matching source road context required')
    source_hash = digest(source)
    if context.get('source_context_hash') != source_hash or receipt.get('source_context_hash') != source_hash:
        raise ValueError('source road context hash mismatch')
    if receipt.get('via') != 'lawagent_a2a' or not receipt.get('law_task_id'):
        raise ValueError('Law task receipt required')
    identity = receipt.get('input_identity') or {}
    if receipt.get('input_hash') != digest(identity):
        raise ValueError('Law input hash mismatch')
    target = (request.get('options') or {}).get('target_parking_stalls')
    if target is None:
        target = (request.get('law') or {}).get('required_spaces')
    expected_identity = dict(pnu=request.get('pnu'), facts=source.get('facts'), total_spaces=target,
                             structure='surface', parking_angle=source.get('parking_angle'),
                             assessment_date=source.get('assessment_date') or date.today().isoformat())
    if digest(identity) != digest(expected_identity) or digest(context.get('facts')) != digest(source.get('facts')):
        raise ValueError('Law receipt does not match design inputs')
    current = evaluate(**identity)
    for key in ('status', 'input_hash', 'source_snapshot_hash', 'policy_id', 'max_total_spaces',
                'required_combined_aisle_width_m', 'allowed_extent'):
        if receipt.get(key) != current.get(key):
            raise ValueError('stale or modified Law receipt: ' + key)
    if current['status'] != 'applicable_for_preliminary_design':
        return {'status': current['status'], 'reason': 'Law applicability unresolved', 'law': current}
    refs = source.get('source_refs')
    if not isinstance(refs, list) or not refs or not all(isinstance(r, str) and r.strip() for r in refs):
        raise ValueError('source road geometry references required')
    source_crs = CRS.from_user_input(context['source_coordinate_crs'])
    metric_crs = CRS.from_user_input(request['crs'])
    if not metric_crs.is_projected or any(abs(a.unit_conversion_factor-1)>EPS for a in metric_crs.axis_info):
        raise ValueError('metre coordinate system required')
    if source.get('crs') is not None and CRS.from_user_input(source['crs']) != source_crs:
        raise ValueError('source road CRS mismatch')
    origin = request['origin_utm']
    if len(origin) != 2 or not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in origin):
        raise ValueError('metric origin required')
    projection = Transformer.from_crs(source_crs, metric_crs, always_xy=True)
    geoms = {}
    for key in ('road_polygon', 'included_road_polygon', 'frontage', 'painted_centreline'):
        if key == 'painted_centreline' and current['allowed_extent'] != 'centreline':
            continue
        raw = shape(source[key])
        drawn = shape(context[key])
        expected = translate(transform(projection.transform, raw), xoff=-origin[0], yoff=-origin[1])
        if (drawn.is_empty or not drawn.is_valid or expected.is_empty or not expected.is_valid
                or drawn.geom_type != expected.geom_type or drawn.hausdorff_distance(expected) > EPS
                or abs(drawn.area-expected.area) > EPS):
            raise ValueError('derived road geometry differs from source: ' + key)
        geoms[key] = drawn
    road = polygon(geoms['road_polygon'])
    included = polygon(geoms['included_road_polygon'])
    site = polygon(request['site'])
    frontage = geoms['frontage']
    if frontage.geom_type not in ('LineString','MultiLineString') or frontage.length <= EPS:
        raise ValueError('source frontage must be a line')
    authorized = shape(request['frontage'])
    if (not site.boundary.buffer(EPS).covers(frontage) or not road.buffer(EPS).covers(frontage)
            or not authorized.buffer(EPS).covers(frontage) or not included.buffer(EPS).covers(frontage)
            or road.intersection(site).area > EPS or not road.buffer(EPS).covers(included)):
        raise ValueError('source road extent or frontage is inconsistent with parcel')
    if current['allowed_extent'] == 'centreline':
        line = geoms['painted_centreline']
        if line.geom_type not in ('LineString','MultiLineString') or line.is_empty:
            raise ValueError('actual painted centreline required')
        if not _centreline_bounds_frontage(road, frontage, line):
            raise ValueError('straight frontage-to-centreline road corridor cannot be certified')
        near = []
        for component in parts(road):
            if component.boundary.intersection(frontage.buffer(EPS)).length <= EPS:
                continue
            pieces = [component]
            for cutter in getattr(line, 'geoms', [line]):
                pieces = [piece for item in pieces for piece in parts(split(item, cutter))]
            local = [p for p in pieces if p.boundary.intersection(frontage.buffer(EPS)).length > EPS]
            if len(pieces) <= len(local):
                raise ValueError('painted centreline must divide each frontage road component')
            near.extend(local)
        allowed = unary_union(near)
        if allowed.is_empty or not allowed.buffer(EPS).covers(included):
            raise ValueError('included road must stay on parcel side of painted centreline')
    return dict(status='ready', road=road, included=included, frontage=frontage,
                required_width_m=current['required_combined_aisle_width_m'],
                max_total_spaces=current['max_total_spaces'], law=current)


def certify(request, features):
    result = dict(stall_ids=set(), exterior=Polygon(), checks=[], area_m2=0.)
    external = [f for f in features if (f.get('properties') or {}).get('layer') == 'external_road_aisle']
    claimed = [f for f in features if (f.get('properties') or {}).get('layer') == 'parking_stall'
               and (f.get('properties') or {}).get('access_kind') == 'road_aisle']
    if not external and not claimed:
        return result

    def check(key, ok, **details):
        result['checks'].append(dict(id='road_aisle:'+key, status='passed' if ok else 'failed', **details))
        return ok

    bound = scope(request)
    if not check('source_and_law', bound['status']=='ready', reason=bound.get('reason')):
        return result
    if not check('supported_angle', bound['law']['input_identity']['parking_angle']=='perpendicular',
                 reason='parallel road aisle maneuver cells are not implemented'):
        return result
    try:
        from backend.app.modules.law.reference.road_aisle import evaluate
        from .legal_siting import building_parking
        from .pedestrian import pedestrian_reservation
        stalls = [f for f in features if (f.get('properties') or {}).get('layer') == 'parking_stall']
        identity = dict(bound['law']['input_identity'], total_spaces=len(stalls),
                        structure='building' if building_parking(features) else 'surface')
        actual = evaluate(**identity)
        if not check('actual_layout_applicability', actual['status']=='applicable_for_preliminary_design',
                     provided=len(stalls), applicability=actual['status']):
            return result
        exterior = unary_union([polygon(f['geometry']) for f in external])
        site = polygon(request['site'])
        if not check('external_extent', bool(external) and all(f['properties'].get('level',0)==0 for f in external)
                     and bound['included'].buffer(EPS).covers(exterior) and exterior.intersection(site).area <= EPS):
            return result
        drive = unary_union([exterior, *[shape(f['geometry']) for f in features
            if (f.get('properties') or {}).get('level',0)==0
            and f['properties'].get('layer') in ('parking_aisle','vehicular_access')]])
        obstacles = [shape(g) for g in request.get('columns', [])]
        if request.get('core'):
            obstacles.append(shape(request['core']))
        obstacles += [shape(f['geometry']) for f in features if f['properties'].get('layer') in
                      ('building_footprint','building_core','column','ramp')]
        obstacles.append(pedestrian_reservation(request)['vehicle_blocked'])
        clear_drive = drive.difference(unary_union(obstacles))
        prohibited = shape(request['vehicle_prohibited']) if request.get('vehicle_prohibited') else Polygon()
        required = bound['required_width_m']
        seen = set()
        for f in stalls:
            props = f['properties']
            if props.get('level',0) != 0:
                continue
            stall = polygon(f['geometry'])
            sid = props.get('stall_id')
            rect = stall.minimum_rotated_rectangle
            coords = list(rect.exterior.coords)
            lengths = [math.dist(a,b) for a,b in zip(coords,coords[1:])]
            face_length = max(lengths) if identity['parking_angle']=='parallel' else min(lengths)
            served = False
            for a,b in zip(coords,coords[1:]):
                length = math.dist(a,b)
                if abs(length-face_length)>EPS:
                    continue
                midpoint=((a[0]+b[0])/2,(a[1]+b[1])/2)
                nx,ny=-(b[1]-a[1])/length,(b[0]-a[0])/length
                if nx*(midpoint[0]-stall.centroid.x)+ny*(midpoint[1]-stall.centroid.y)<0:
                    nx,ny=-nx,-ny
                cell=Polygon([a,b,(b[0]+nx*required,b[1]+ny*required),(a[0]+nx*required,a[1]+ny*required)])
                if (clear_drive.buffer(EPS).covers(cell) and cell.intersection(exterior).area>EPS
                        and cell.intersection(bound['frontage']).length>=length-EPS
                        and cell.intersection(bound['frontage']).intersection(prohibited.buffer(EPS)).length<=EPS):
                    served = True
                    break
            tagged = props.get('access_kind')=='road_aisle'
            if tagged or served:
                valid = (served and sid is not None and sid not in seen and site.buffer(EPS).covers(stall)
                         and props.get('type') != 'standard_parallel')
                valid = valid and stall.symmetric_difference(rect).area<=EPS
                if check('combined_width:'+str(sid), valid, required_width_m=required):
                    result['stall_ids'].add(sid)
                seen.add(sid)
        check('serves_stalls', bool(result['stall_ids']))
        result.update(exterior=exterior, area_m2=exterior.area)
    except (ValueError,TypeError,KeyError,AttributeError) as exc:
        check('geometry',False,reason=str(exc))
    return result
