import math

from shapely.affinity import scale
from shapely.errors import GEOSException
from shapely.geometry import shape

from backend.app.modules.land.projection import wgs84_to_utm
from ..job_defaults import FLOOR_HEIGHTS
from .geometry import CandidateRejected, build_additive, finite, polygon, reject
from .repair import resolve_limits, repair_geometry, envelope_geometry
from .renderer import render_candidate


METRICS = {'floor_area':'floor_area','daylight_score':'daylight_score','bcr':'bcr','far':'far',
           'height':'height','setback':'min_setback','building_line_setback':'min_setback',
           'landscaping_pct':'open_pct','compactness':'compactness','stepback_factor':'stepback_factor'}


def validate_context(prepared, *, limits=None, envelope=None):
    try:
        if prepared.get('algorithm') != 'additive':
            reject('unsupported_algorithm', 'Only additive computation is supported')
        building_type = prepared['building_type']
        if building_type not in FLOOR_HEIGHTS:
            reject('unsupported_building_type', 'Building use is unsupported')
        floor_height = FLOOR_HEIGHTS[building_type]
        site, reduced = polygon(wgs84_to_utm(shape(prepared['site_polygon'])))
        if reduced:
            reject('unsupported_site', 'Multipart sites are unsupported')
        site_area = prepared['site_area_m2']
        if not finite(site_area) or site_area <= 0 or abs(round(site.area,2)-site_area) > 0.011:
            reject('invalid_site_area', 'Saved area does not match projected site')
        outputs = prepared['job_spec']['outputs']
        if not isinstance(outputs, list) or not outputs or len(outputs) > 40:
            reject('invalid_outputs', 'Expected bounded output definitions')
        for definition in outputs:
            if definition.get('name') not in METRICS or definition.get('type') not in ('Objective','Constraint'):
                reject('unsupported_metric', 'Requested output metric is unsupported')
            if definition['type'] == 'Objective' and definition.get('Goal') not in ('Minimize','Maximize'):
                reject('invalid_objective', 'Objective direction is unsupported')
            if definition['type'] == 'Constraint' and (not finite(definition.get('val')) or definition.get('Requirement') not in ('Less than','Greater than','Equals')):
                reject('invalid_constraint', 'Constraint is invalid')
        resolved, provenance = resolve_limits(outputs,floor_height,limits)
        envelope_geometry(envelope)
        return site, site_area, building_type, floor_height, outputs, resolved, provenance
    except CandidateRejected:
        raise
    except (GEOSException, ValueError, TypeError, KeyError, IndexError, OverflowError, AttributeError):
        reject('invalid_context', 'Candidate computation context is invalid')


def evaluate_candidate(inputs, prepared, *, limits=None, envelope=None):
    result = {'outputs':[], 'metrics':{}, 'geometry':None, 'repair':{}, 'rejections':[], 'constraint_violations':[]}
    try:
        site, site_area, building_type, floor_height, outputs, resolved, provenance = validate_context(prepared,limits=limits,envelope=envelope)
        result['repair'] = {**provenance, 'limits':resolved, 'actions':[]}
        built, reduced = build_additive(inputs,site)
        footprint, floors, actions = repair_geometry(built.intersection(site),site,max(1,round(inputs[25][0])),resolved,envelope)
        if reduced:
            actions.insert(0,'disconnected_boxes_to_largest')
        result['repair']['actions'] = actions
        upper_scale = max(0.5,min(1.0,inputs[27][0]))
        step_fraction = max(0.3,min(0.8,inputs[28][0]))
        has_stepback = floors >= 2 and upper_scale < 0.98 and step_fraction < 0.95
        upper = None
        step_floor = None
        if has_stepback:
            step_floor = max(1,round(floors*step_fraction))
            upper, reduced_upper = polygon(scale(footprint,xfact=upper_scale,yfact=upper_scale,origin='centroid').intersection(site))
            if reduced_upper or upper.difference(footprint).area > 1e-7:
                reject('unsupported_upper_topology', 'Scaled upper plate extends outside the base footprint')
            floor_area = footprint.area*step_floor+upper.area*(floors-step_floor)
        else:
            floor_area = footprint.area*floors
        open_ratio = 1-footprint.area/site_area
        perimeter_ratio = footprint.length/math.sqrt(footprint.area)
        bonus = (1-upper_scale)*0.3 if has_stepback else 0
        metrics = {'floor_area':round(floor_area,2),
                   'daylight_score':round(min((open_ratio*0.5+min(perimeter_ratio/8,1)*0.3+bonus+0.2)*100,100),2),
                   'bcr':round(footprint.area/site_area*100,2), 'far':round(floor_area/site_area*100,2),
                   'height':round(floors*floor_height,2),
                   'min_setback':round(footprint.distance(site.boundary) if site.contains(footprint) else 0,2),
                   'open_pct':round(open_ratio*100,2), 'compactness':round(footprint.length**2/footprint.area,2),
                   'stepback_factor':round(1-upper_scale,4) if has_stepback else 0.0}
        values = []
        for definition in outputs:
            if definition['name'] not in METRICS:
                reject('unsupported_metric', 'Requested output metric is unsupported')
            value = metrics[METRICS[definition['name']]]
            if definition['type'] == 'Constraint':
                target = definition['val']
                direction = definition['Requirement']
                if not finite(target) or direction not in ('Less than','Greater than','Equals'):
                    reject('invalid_constraint', 'Constraint is invalid')
                if ((direction == 'Less than' and value > target) or (direction == 'Greater than' and value < target)
                        or (direction == 'Equals' and value != target)):
                    result['constraint_violations'].append({'name':definition['name'],'value':value,'requirement':direction,'target':target})
            values.append(value)
        if not all(finite(value) for value in (*values,*metrics.values())):
            reject('nonfinite_metrics', 'Candidate metrics are not finite')
        result.update(outputs=values,metrics=metrics,geometry=render_candidate(footprint,floors,floor_height,building_type,
            site_area,metrics,upper=upper,upper_scale=upper_scale,step_floor=step_floor))
    except CandidateRejected as error:
        result['rejections'].append({'code':error.code,'message':str(error)})
    except (GEOSException, ValueError, TypeError, KeyError, IndexError, OverflowError):
        result['rejections'].append({'code':'invalid_candidate','message':'Candidate input or geometry is invalid'})
    return result
