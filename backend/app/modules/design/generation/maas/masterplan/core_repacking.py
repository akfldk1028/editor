"""Repack around a proposed core while retaining actual ramp geometry."""
from copy import deepcopy
import math
from shapely.geometry import shape, Polygon
from backend.app.modules.design.generation.maas.masterplan.geometry import feature, union_or_empty, digest
from backend.app.modules.design.generation.maas.masterplan.core_repair import core_obstacle
from backend.app.modules.design.generation.maas.masterplan.pedestrian import profile_flat_area
from backend.app.modules.design.generation.maas.masterplan.basement_layout import solve_basement_level
from backend.app.modules.design.generation.maas.masterplan.program import declared_rooms
from backend.app.modules.design.generation.maas.masterplan.validation import validate_plan
from backend.app.modules.design.generation.maas.masterplan.layout_axis import layout_axis_angle
from backend.app.modules.design.generation.maas.masterplan.planner import program_features, level_efficiency, excavation_cost_units


def repack_core(request, result):
    if request.get('options', {}).get('allow_core_repair') is not True:
        raise ValueError('core repacking requires explicit allow_core_repair')
    opts, rules = request['options'], request['rules']
    source = result['features']
    levels = sorted({f['properties'].get('level', 0) for f in source if f['properties']['layer']=='basement_boundary'}, reverse=True)
    if not levels:
        # A pure surface scheme uses the ordinary owner solver.
        from backend.app.modules.design.generation.maas.masterplan.planner import plan_site
        return plan_site(request)
    if len(levels) > opts.get('max_basement_levels', 1):
        raise ValueError('frozen ramp levels exceed authorized basement limit')
    core = shape(request['core'])
    obstacles = union_or_empty([core_obstacle(request), *[shape(c) for c in request.get('columns', [])]])
    envelope = shape(request.get('basement_boundary') or request['site'])
    removed = {'parking_stall', 'parking_aisle', 'basement_plant_zone', 'basement_room', 'basement_boundary'}
    features = [deepcopy(f) for f in source if f['properties']['layer'] != 'building_core'
                and not (f['properties'].get('level', 0) < 0 and f['properties']['layer'] in removed)]
    core_levels = {f['properties'].get('level', 0) for f in source if f['properties']['layer']=='building_core'}
    features += [feature('building_core', core, lv, z_m=lv*opts['basement_floor_height_m']) for lv in sorted(core_levels)]
    total = sum(f['properties']['layer']=='parking_stall' for f in features)
    accessible = sum(f['properties']['layer']=='parking_stall' and f['properties'].get('type')=='accessible' for f in features)
    target = max(request['law'].get('required_spaces') or 0, opts.get('target_parking_stalls') or 0)
    required_accessible = request['law'].get('required_accessible_spaces') or 0
    meta = [deepcopy(v) for v in result.get('levels', []) if v['level'] >= 0]
    angle = layout_axis_angle(request)
    if angle is None:
        road = shape(request['frontage'])
        lines = [road] if road.geom_type == 'LineString' else list(getattr(road, 'geoms', ()))
        segments = [(a, b) for line in lines if line.geom_type == 'LineString'
                    for a, b in zip(line.coords, list(line.coords)[1:]) if math.dist(a, b) > 0]
        if not segments:
            raise ValueError('core repacking requires a nonzero frontage segment or explicit layout_axis')
        a, b = max(segments, key=lambda pair: math.dist(*pair))
        angle = math.degrees(math.atan2(b[1]-a[1], b[0]-a[0]))
    for lv in levels:
        incoming = next(f for f in source if f['properties']['layer']=='ramp' and f['properties'].get('to_level')==lv)
        rp, geom = incoming['properties'], shape(incoming['geometry'])
        center = next(shape(f['geometry']) for f in source if f['properties']['layer']=='ramp_centerline'
                      and f['properties'].get('to_level')==lv)
        lower = profile_flat_area(geom, center, rp['profile'], rp['width_m'], rp['profile'][-1]['z_m'])
        upper = profile_flat_area(geom, center, rp['profile'], rp['width_m'], rp['profile'][0]['z_m'])
        ramp = {'polygon': geom, 'lower_landing': lower, 'upper_landing': upper}
        departure = next((f for f in source if f['properties']['layer']=='ramp'
                          and f['properties'].get('from_level')==lv), None)
        departure_landing = None
        if departure:
            dp = departure['properties']
            dc = next(shape(f['geometry']) for f in source if f['properties']['layer']=='ramp_centerline'
                      and f['properties'].get('from_level')==lv)
            departure_landing = profile_flat_area(shape(departure['geometry']), dc, dp['profile'], dp['width_m'], dp['profile'][0]['z_m'])
        expanded = math.ceil(target*float(rules.get('expanded_min_share') or 0))
        already = sum(f['properties'].get('type')=='expanded' for f in features if f['properties']['layer']=='parking_stall')
        solved = solve_basement_level(envelope, ramp, obstacles, declared_rooms(opts) if lv==-1 else [], rules,
            max(0, target-total), max(0, required_accessible-accessible), angle=angle,
            expanded_needed=max(0, expanded-already), field=opts.get('basement_parking_field', 'auto'),
            turn_radius_m=(opts.get('vehicle') or {}).get('turning_radius_outer_m'),
            turn_lane_m=opts.get('turn_lane_m'),
            departure_landing=departure_landing, require_full_width=True)
        if solved is None:
            raise ValueError(f'no repacking with full-width access at level {lv}')
        zone, parking = solved['zone'], solved['parking']
        z = lv*opts['basement_floor_height_m']
        # The parking plate may be smaller than an authored ramp. Retain the
        # ramp's actual excavation just as the ordinary planner does.
        serving_ramps = [shape(f['geometry']) for f in source if f['properties']['layer']=='ramp'
                         and lv in (f['properties'].get('from_level'), f['properties'].get('to_level'))]
        dug = union_or_empty([envelope, *serving_ramps]).intersection(shape(request['site']))
        features.append(feature('basement_boundary', dug, lv, z_m=z))
        features += program_features(zone, lv, z)
        for i, stall in enumerate(parking['stalls'], 1):
            features.append(feature('parking_stall', stall['polygon'], lv, stall_id=f'B{-lv}-P{i:03d}',
                type=stall['type'], width_m=stall['width_m'], length_m=stall['length_m'], z_m=z))
        if not parking['drive'].is_empty:
            features.append(feature('parking_aisle', parking['drive'], lv, width_m=rules['aisle_width_m'], z_m=z))
        total += parking['provided']
        accessible += parking['accessible']
        meta.append({'level': lv, 'z_m': z, 'provided_spaces': parking['provided'],
                     'plate_area_m2': dug.area-(zone['zone'].area if zone else 0)})
    checked = validate_plan(request, {'features': features})
    blocking = [v for v in result.get('blocking', []) if not v.startswith((
        'parking shortfall:', 'validation:', 'explicit practice brief:', 'core_vehicle_clearance:', 'core_repair_full_width_drive:'))]
    blocking += checked.get('pending_reviews', [])
    if checked.get('geometry_status') == 'needs_evidence' or any(c.get('status') == 'needs_evidence' for c in checked['checks']):
        blocking.append('validation: needs_evidence')
    failed = [c['id'] for c in checked['checks'] if c['status']=='failed']
    blocking += failed
    if total < target:
        blocking.append(f'parking shortfall: {total} of design target {target} stalls placed')
    status = 'needs_revision' if failed or total < target else 'needs_evidence' if blocking else 'resolved'
    stats = level_efficiency(features, rules)
    for row in meta:
        if row['level'] in stats:
            row.update(stats[row['level']])
    metrics = deepcopy(result.get('metrics', {}))
    excavation = union_or_empty([shape(f['geometry']) for f in features
                                 if f['properties']['layer']=='basement_boundary']).area
    metrics.update(provided_parking_stalls=total, provided_accessible_stalls=accessible,
        excavation_m2=round(excavation, 2), excavation_cost_units=excavation_cost_units(excavation, len(levels)),
        area_per_stall_m2=round(sum(v['parking_area_m2'] for v in stats.values()) /
                               max(sum(v['stalls'] for v in stats.values()), 1), 2) if stats else None,
        excavation_over_footprint=round(excavation/shape(request['footprint']).area, 3)
                                  if shape(request['footprint']).area else None,
        basement_levels=len(levels), parking_status=checked['geometry_status'], layout_pattern='core_repacked',
        layout_score=None, layout_terms=None, original_excavation_m2=(result.get('metrics') or {}).get('excavation_m2'))
    return {'schema_version':'masterplan.layout.v1', 'type':'FeatureCollection', 'pnu': request['pnu'],
        'coordinate_crs': request['crs'], 'features': features, 'levels': meta, 'metrics': metrics,
        'validation': checked, 'status': status, 'blocking': list(dict.fromkeys(blocking)),
        'provenance': {'law': request['law'], 'rules': rules, 'evidence': request.get('evidence', {}),
                       'repair': 'existing ramp retained; core and basement programme/parking repacked'},
        'handoff': {'input_hash':digest(request), 'geometry_hash':digest(features), 'hard_pass':False,
                    'status':'failed' if status=='needs_revision' else 'needs_evidence', 'evaluated':True},
        'alternatives': []}
