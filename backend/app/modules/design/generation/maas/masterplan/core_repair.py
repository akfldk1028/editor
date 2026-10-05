"""Explicit preliminary core-zone proposals; no detailed floor-plan authorship."""
from copy import deepcopy
import math
from shapely.affinity import rotate, translate
from shapely.geometry import Polygon, mapping, shape
from backend.app.modules.design.generation.maas.masterplan.geometry import EPS, digest, number, parts, union_or_empty


def clearance(request):
    opts = request.get('options') or {}
    val = opts.get('core_vehicle_clearance_m')
    if val is None and (opts.get('planning_stage') == 'placement' or opts.get('enforce_pedestrian_buffer')):
        val = 2.0
    return number(val if val is not None else 0,
                  'core vehicle clearance', maximum=10)


def core_obstacle(request):
    core = shape(request['core']) if request.get('core') else Polygon()
    return core.buffer(clearance(request), join_style=2) if not core.is_empty else core


def propose_core_repairs(request, result, limit=4):
    if type(limit) is not int or not 1 <= limit <= 12:
        raise ValueError('core proposal limit must be 1..12')
    report = {'schema_version': 'arr.core-repair-proposals.v1', 'input_hash': digest(request),
              'geometry_hash': digest(result.get('features', [])), 'candidates': []}
    if (request.get('options') or {}).get('allow_core_repair') is not True:
        return {**report, 'reason': 'core_changes_not_authorized'}
    if not request.get('core') or not request.get('footprint'):
        return {**report, 'reason': 'authored_core_and_footprint_required'}
    original = shape(request['core'])
    pieces = parts(original)
    host = shape(request.get('ground_footprint') or request['footprint']).intersection(shape(request['footprint']))
    columns = union_or_empty([shape(c) for c in request.get('columns', [])])
    margin = clearance(request)
    rect = list(pieces[0].minimum_rotated_rectangle.exterior.coords)
    a, b = max(zip(rect, rect[1:]), key=lambda e: math.dist(*e))
    angle = (math.degrees(math.atan2(b[1]-a[1], b[0]-a[0])) - 90) % 180
    aligned = [rotate(p, -angle, origin=(0, 0)) for p in pieces]
    # Rigid relocation preserves existing separation; compact arrangements are
    # alternatives, preserving each core area/shape/count and vertical alignment.
    templates = [('rigid', union_or_empty(aligned))]
    for turn in (0, 90):
        placed, x = [], 0.
        for p in aligned:
            p = rotate(p, turn, origin='centroid')
            x0, y0, x1, _ = p.bounds
            placed.append(translate(p, xoff=x-x0, yoff=-y0))
            x += x1-x0 + max(margin, EPS*10)
        templates.append((f'regroup_{turn}', union_or_empty(placed)))
    local_host = rotate(host, -angle, origin=(0, 0))
    hx0, hy0, hx1, hy1 = local_host.bounds
    vehicles, bays, programmes = [], [], []
    for f in result.get('features', []):
        layer = f.get('properties', {}).get('layer')
        if layer in ('parking_aisle', 'vehicular_access', 'ramp'):
            vehicles.append(shape(f['geometry']))
        elif layer == 'parking_stall':
            bays.append(shape(f['geometry']))
        elif layer == 'basement_plant_zone':
            programmes.append(shape(f['geometry']))
    vehicle = union_or_empty(vehicles)
    programme = union_or_empty(programmes)
    choices, seen = [], set()
    for kind, template in templates:
        x0, y0, x1, y1 = template.bounds
        w, h = x1-x0, y1-y0
        for ix in range(9):
            for iy in range(9):
                x, y = hx0+(hx1-hx0-w)*ix/8, hy0+(hy1-hy0-h)*iy/8
                g = rotate(translate(template, xoff=x-x0, yoff=y-y0), angle, origin=(0, 0))
                key = digest(mapping(g))
                if key in seen or g.equals_exact(original, EPS):
                    continue
                seen.add(key)
                if (len(parts(g)) != len(pieces) or not host.buffer(EPS).covers(g)
                        or g.intersection(columns).area > EPS):
                    continue
                reserved = g.buffer(margin, join_style=2)
                clashes = sum(b.intersection(reserved).area > EPS for b in bays)
                score = (round(reserved.intersection(vehicle).area, 3), clashes,
                         round(reserved.intersection(programme).area, 3),
                         round(original.centroid.distance(g.centroid), 3))
                choices.append((score, kind, g))
    ordered = sorted(choices, key=lambda v: v[0])
    # Spend the bounded solve budget on different arrangements, not three
    # nearly identical translations from the first screened family.
    families = {}
    for choice in ordered:
        families.setdefault(choice[1], choice)
    diverse = sorted(families.values(), key=lambda v: v[0])
    selected = []
    for score, kind, g in [*diverse, *ordered]:
        if any(g.hausdorff_distance(old) < max(margin, 1.) for old in selected):
            continue
        selected.append(g)
        trial = deepcopy(request)
        trial['core'] = mapping(g)
        trial.setdefault('evidence', {})['core'] = {
            'source': 'ARR preliminary automatic core-zone repair', 'parent_core_hash': digest(request['core']),
            'operation': kind, 'detailed_plan_verified': False}
        report['candidates'].append({'id': f'core_{len(selected)}', 'request': trial,
            'screen_score': list(score), 'operation': kind,
            'original_area_m2': original.area, 'proposed_area_m2': g.area, 'core_count': len(pieces)})
        if len(selected) >= limit:
            break
    return report
