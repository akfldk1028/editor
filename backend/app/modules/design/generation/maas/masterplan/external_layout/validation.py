"""Keep source geometry intact; geometry acceptance is not design acceptance."""
import re

from shapely.affinity import rotate, translate
from shapely.geometry import box

from ..geometry import EPS, digest, feature, number, polygon, union_or_empty


def validate_external_layout(draft):
    if not isinstance(draft, dict) or draft.get('schema_version') != 'masterplan.external-layout.v1':
        raise ValueError('unsupported external layout schema')
    if draft.get('coordinate_frame') != 'local_xy_m' or draft.get('rotation_convention') != 'ccw_degrees':
        raise ValueError('explicit local metric coordinates and CCW degrees required')
    source = draft.get('source')
    if (not isinstance(source, dict)
            or not all(isinstance(source.get(k), str) and source[k].strip() for k in ('provider', 'revision'))
            or not re.fullmatch('[0-9a-f]{64}', str(source.get('input_sha256', '')))):
        raise ValueError('provider revision and input SHA256 required')
    site = polygon(draft['site'], 'site')
    if not isinstance(draft.get('obstacles'), list):
        raise ValueError('explicit obstacle list required')
    obstacles = union_or_empty(polygon(p, 'obstacle') for p in draft['obstacles'])
    buildings = draft.get('buildings')
    if not isinstance(buildings, list) or not 1 <= len(buildings) <= 1000:
        raise ValueError('one to 1000 buildings required')
    footprints, features, checks, ids = [], [], [], set()
    for b in buildings:
        if not isinstance(b, dict) or not isinstance(b.get('id'), str) or not b['id'].strip() or b['id'] in ids:
            raise ValueError('unique nonempty building IDs required')
        ids.add(b['id'])
        center = b.get('center_m')
        if not isinstance(center, list) or len(center) != 2:
            raise ValueError('center_m requires two metric coordinates')
        x, y = [number(v, 'center', minimum=-float('inf')) for v in center]
        width, depth, height = [number(b[k], k, minimum=EPS) for k in ('width_m', 'depth_m', 'height_m')]
        angle = number(b['rotation_deg'], 'rotation_deg', minimum=-float('inf'))
        footprint = translate(rotate(box(-width / 2, -depth / 2, width / 2, depth / 2),
                                     angle, origin=(0, 0)), xoff=x, yoff=y)
        polygon(footprint, 'converted building')
        features.append(feature('building_footprint', footprint, building_id=b['id'], height_m=height))
        outside = footprint.difference(site).area
        checks.append({'kind': 'site_containment', 'building_id': b['id'],
                       'status': 'passed' if site.buffer(EPS).covers(footprint) else 'failed',
                       'outside_area_m2': outside})
        overlap = footprint.intersection(obstacles).area
        checks.append({'kind': 'obstacle_overlap', 'building_id': b['id'],
                       'status': 'passed' if overlap <= EPS ** 2 else 'failed', 'overlap_area_m2': overlap})
        for other_id, other in footprints:
            overlap = footprint.intersection(other).area
            checks.append({'kind': 'building_overlap', 'building_ids': [other_id, b['id']],
                           'status': 'passed' if overlap <= EPS ** 2 else 'failed', 'overlap_area_m2': overlap})
        footprints.append((b['id'], footprint))
    return {'schema_version': 'masterplan.external-layout-validation.v1', 'input_hash': digest(draft),
            'geometry_status': 'failed' if any(c['status'] == 'failed' for c in checks) else 'passed',
            'planning_status': 'unknown', 'legal_status': 'unknown', 'daylight_status': 'unknown',
            'features': features, 'checks': checks,
            'scope': 'Rectangle containment and overlap only; source identity is caller-declared, not certified.'}
