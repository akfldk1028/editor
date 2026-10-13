"""Independent dimensional observations, kept separate from legal road status."""
import math
from shapely.geometry import shape
from shapely.ops import linemerge, unary_union


def parking_applicability(rules, count, has_building_parking):
    owner = rules.get('owner_snapshot') or {}
    applicability = owner.get('applicability') or {}
    bounds = applicability.get('installed_spaces_range')
    requested = applicability.get('requested') or {}
    if not bounds:
        return {'status':'needs_evidence', 'reason':'installed_count_applicability_missing', 'provided':count}
    matches = (count >= bounds['minimum'] and (bounds.get('maximum') is None or count <= bounds['maximum'])
               and not (has_building_parking and requested.get('structure') == 'surface'))
    return {'status':'matched' if matches else 'needs_evidence', 'provided':count,
            'installed_spaces_range':bounds, 'has_building_parking':has_building_parking,
            'requested_structure':requested.get('structure'),
            'reason':None if matches else 'actual_layout_requires_new_LawAgent_rules'}


def building_parking(features):
    from .geometry import EPS
    roofs = unary_union([shape(f['geometry']) for f in features
                         if (f.get('properties') or {}).get('layer') == 'building_footprint'])
    for f in features:
        props = f.get('properties') or {}
        if props.get('layer') == 'parking_stall':
            if props.get('level', 0) != 0 or shape(f['geometry']).intersection(roofs).area > EPS:
                return True
    return False


def measure(request):
    receipt = (request.get('law') or {}).get('siting_requirements') or {}
    criteria = receipt.get('criteria') if receipt.get('pnu') == request.get('pnu') and receipt.get('status') == 'criteria_available' else None
    observations = []
    boundary = shape(request['site']).boundary
    for edge in ((request.get('evidence') or {}).get('road_context') or {}).get('edges') or []:
        try:
            contact = shape(edge['geometry']).intersection(boundary)
            lines = [g for g in getattr(contact, 'geoms', [contact]) if g.geom_type == 'LineString']
            merged = linemerge(unary_union(lines)) if len(lines) > 1 else (lines[0] if lines else None)
            length = max((g.length for g in getattr(merged, 'geoms', [merged]) if g is not None), default=0)
            width = edge.get('width_m')
            known_width = isinstance(width, (int, float)) and not isinstance(width, bool) and math.isfinite(width) and width > 0
            status = 'unknown'
            if criteria:
                if length < criteria['min_frontage_m'] or (known_width and width < criteria.get('min_road_width_m', 0)):
                    status = 'shortfall'
                elif not criteria.get('min_road_width_m') or known_width:
                    status = 'dimensions_satisfied'
            observations.append({'road_id':edge.get('road_id'), 'source':edge.get('source'),
                'continuous_contact_m':length, 'road_width_m':width if known_width else None,
                'dimension_status':status, 'legal_road_status':'unverified'})
        except (ValueError, TypeError, KeyError):
            observations.append({'dimension_status':'unknown', 'reason':'invalid_road_geometry'})
    return {'status':'needs_evidence', 'criteria':criteria, 'observations':observations,
        'law_task_id':receipt.get('law_task_id'), 'source':receipt.get('source'),
        'missing_evidence':list(dict.fromkeys([*(receipt.get('missing_evidence') or []),
            'building_act_road_classification', 'not_motorway_only', 'legal_road_frontage_review'])),
        'scope':'GIS dimensions only; cadastral road use and proximity do not certify a Building Act road',
        'permit_compliance_verified':False}
