import math

from shapely.affinity import scale
from shapely.geometry import Polygon, box

from backend.app.modules.land.projection import wgs84_to_utm
from .geometry import finite, polygon, reject


DEFAULTS = {'bcr_limit_pct':80.0, 'far_limit_pct':1300.0, 'height_limit_m':50.0,
            'adjacent_setback_m':1.0, 'road_setback_m':3.0, 'north_setback_m':1.5}
CONSTRAINT_LIMITS = {'bcr':('bcr_limit_pct','Less than'), 'far':('far_limit_pct','Less than'),
                     'height':('height_limit_m','Less than'), 'setback':('adjacent_setback_m','Greater than'),
                     'building_line_setback':('road_setback_m','Greater than')}


def resolve_limits(outputs, floor_height, overrides=None):
    values = dict(DEFAULTS)
    supplied = set()
    for item in outputs:
        if item.get('type') != 'Constraint' or item.get('name') not in CONSTRAINT_LIMITS:
            continue
        key, direction = CONSTRAINT_LIMITS[item['name']]
        if item.get('Requirement') != direction:
            reject('unsupported_repair_constraint', 'Constraint direction is unsupported by additive repair')
        values[key] = item['val']
        supplied.add(key)
    if overrides is not None:
        if not isinstance(overrides, dict) or set(overrides) - set(DEFAULTS):
            reject('invalid_repair_limits', 'Unsupported repair limit fields')
        for key, value in overrides.items():
            if key in supplied and value != values[key]:
                reject('conflicting_repair_limits', 'Explicit repair limits conflict with specification')
            values[key] = value
            supplied.add(key)
    for key, value in values.items():
        if not finite(value) or value < 0 or value > 1e9 or (key in ('bcr_limit_pct','far_limit_pct','height_limit_m') and value <= 0):
            reject('invalid_repair_limits', 'Repair limits must be finite and nonnegative, with positive caps')
    values['floor_height_m'] = floor_height
    return values, {'provenance':'user_search_limits' if supplied else 'search_defaults',
                    'defaulted_fields':sorted(set(DEFAULTS)-supplied), 'legal_approval':False}


def envelope_geometry(envelope):
    if envelope is None:
        return None, None
    if not isinstance(envelope, dict) or envelope.get('elevation_source') == 'failed':
        reject('invalid_sunlight_envelope', 'Sunlight envelope evidence is unavailable')
    slanted = envelope.get('slanted_polygons')
    if not isinstance(slanted, list) or not 1 <= len(slanted) <= 100:
        reject('invalid_sunlight_envelope', 'Expected bounded sunlight slanted polygons')
    heights = []
    envelopes = []
    for entry in slanted:
        corners = entry.get('corners') if isinstance(entry, dict) else None
        if not isinstance(corners, list) or not 3 <= len(corners) <= 10000:
            reject('invalid_sunlight_envelope', 'Sunlight envelope corners are invalid')
        for corner in corners:
            if (not isinstance(corner, (list, tuple)) or len(corner) != 3 or not all(finite(v) for v in corner)
                    or not -180 <= corner[0] <= 180 or not -90 <= corner[1] <= 90 or corner[2] <= 0):
                reject('invalid_sunlight_envelope', 'Sunlight corners require finite coordinates and positive heights')
            heights.append(corner[2])
        poly, _ = polygon(wgs84_to_utm(Polygon([(c[0],c[1]) for c in corners])))
        envelopes.append(poly)
    first = envelopes[0]
    if any(first.symmetric_difference(other).area > 0.001 for other in envelopes[1:]):
        reject('unsupported_sunlight_envelope', 'Multiple different sunlight footprints require floorwise projection')
    return first, min(heights)


def repair_geometry(footprint, site, floors, limits, envelope=None):
    actions = []
    footprint, reduced = polygon(footprint)
    if reduced:
        actions.append('multipolygon_to_largest')
    if not site.contains(footprint):
        footprint, reduced = polygon(footprint.intersection(site))
        actions.append('site_clip')
    setback = max(limits['adjacent_setback_m'], limits['road_setback_m'])
    inward = site.buffer(-setback) if setback > 0 else site
    if inward.is_empty or inward.area <= 1:
        reject('empty_setback_region', 'Search setback leaves no usable area')
    if not inward.contains(footprint):
        footprint, reduced = polygon(footprint.intersection(inward))
        actions.append(f'setback_clip_{setback}m')
    minx, miny, maxx, maxy = site.bounds
    if limits['north_setback_m'] > 0:
        y = maxy-limits['north_setback_m']
        if y <= miny:
            reject('empty_north_setback', 'North search setback leaves no usable area')
        clipped, _ = polygon(footprint.intersection(box(minx-1,miny-1,maxx+1,y)))
        if clipped.area < footprint.area:
            footprint = clipped
            actions.append(f"north_setback_{limits['north_setback_m']}m")
    for iteration in range(3):
        bcr = footprint.area/site.area*100
        if bcr <= limits['bcr_limit_pct']:
            break
        factor = math.sqrt(limits['bcr_limit_pct']/bcr)*0.99
        footprint, _ = polygon(scale(footprint,xfact=factor,yfact=factor,origin='centroid').intersection(inward))
        actions.append(f'bcr_clamp_iter{iteration+1}_to_{round(footprint.area/site.area*100,1)}')
    envelope_polygon, height_cap = envelope_geometry(envelope)
    if envelope_polygon is not None and not envelope_polygon.contains(footprint):
        footprint, _ = polygon(footprint.intersection(envelope_polygon))
        actions.append(f'sunlight_envelope_clip_to_{round(envelope_polygon.area,1)}m2')
    height_floors = max(1,int(limits['height_limit_m']/limits['floor_height_m']))
    if floors > height_floors:
        floors = height_floors
        actions.append(f'height_cap_to_{floors}f')
    if footprint.area*floors/site.area*100 > limits['far_limit_pct']:
        floors = min(floors,max(1,int(limits['far_limit_pct']/100*site.area/footprint.area)))
        actions.append(f'far_cap_to_{floors}f')
    if height_cap is not None:
        max_floors = max(1,int(height_cap/max(limits['floor_height_m'],0.1)))
        if floors > max_floors:
            floors = max_floors
            actions.append(f'sunlight_height_cap_to_{floors}f')
    if (footprint.area/site.area*100 > limits['bcr_limit_pct']+1e-8
            or footprint.area*floors/site.area*100 > limits['far_limit_pct']+1e-8
            or floors*limits['floor_height_m'] > limits['height_limit_m']+1e-8
            or (height_cap is not None and floors*limits['floor_height_m'] > height_cap+1e-8)
            or footprint.difference(inward).area > 1e-7):
        reject('repair_constraints_unsatisfied', 'Repaired geometry still exceeds search limits')
    return footprint, floors, actions
