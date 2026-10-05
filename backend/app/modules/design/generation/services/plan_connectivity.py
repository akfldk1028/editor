"""Measured gross-zone topology; shared boundaries are not door/egress proof."""
from shapely.geometry import mapping, shape


def _parts(geometry):
    if geometry.is_empty:
        return []
    if geometry.geom_type == 'Polygon':
        return [geometry]
    if hasattr(geometry, 'geoms'):
        return [part for child in geometry.geoms for part in _parts(child)]
    return []


def _components(geometry):
    return [{'component_index': index, 'area_m2': part.area,
             'geometry': mapping(part)} for index, part in enumerate(_parts(geometry))]


def measure(floors, outputs):
    """Return exact source/variant measurements without changing any geometry."""
    floor_reviews, issues = [], []
    intersection = None
    for floor, output in zip(floors, outputs):
        footprint = shape(floor['body']['footprint_geojson'])
        intersection = footprint if intersection is None else intersection.intersection(footprint)
        components = _components(footprint)
        identity = {key: floor[key] for key in ('program_floor', 'mass_floor', 'section_elevation_m')}
        identity['footprint_hash'] = floor['body']['mass_binding']['footprint_hash']
        variants = []
        for variant in output['results'] + output.get('rejected_candidates', []):
            spaces = [(feature['properties']['space_id'], shape(feature['geometry']))
                      for feature in variant['floor_plan']['features']]
            fragmented = [{'space_id': sid, 'component_count': len(_parts(geometry)),
                           'component_areas_m2': [part.area for part in _parts(geometry)]}
                          for sid, geometry in spaces if len(_parts(geometry)) > 1]
            adjacency = []
            for index, (left_id, left) in enumerate(spaces):
                for right_id, right in spaces[index + 1:]:
                    shared = left.boundary.intersection(right.boundary).length
                    if shared > 0:
                        adjacency.append({'space_ids': [left_id, right_id], 'shared_boundary_m': shared})
            variants.append({'design_id': variant['design_id'],
                             'fragmented_reservations': fragmented,
                             'shared_boundaries': adjacency})
            if fragmented:
                issues.append({**identity, 'code': 'fragmented_gross_reservations',
                    'severity': 'requires_revision', 'affected_outputs': ['plan'],
                    'recommended_agents': ['plan'], 'design_id': variant['design_id'],
                    'space_ids': [row['space_id'] for row in fragmented],
                    'evidence': fragmented,
                    'requested_correction': 'Repartition these reservations into connected usable zones; preserve Program identities and source capacity.'})
        floor_reviews.append({**identity, 'component_count': len(components),
                              'components': components, 'variants': variants})
        if len(components) > 1:
            issues.append({**identity, 'code': 'disconnected_floor_footprint',
                'severity': 'requires_revision', 'affected_outputs': ['geometry.mass', 'plan'],
                'recommended_agents': ['mass', 'masterplan'], 'space_ids': floor['space_ids'],
                'evidence': {'component_count': len(components), 'components': components},
                'requested_correction': 'First qualify occupied versus structural/support components from source construction semantics and revise Program capacity if needed. Only then assess connections or independent occupied parts. Do not connect piers or bridge void by inference.'})
    envelope = {'status': 'placement_envelope_only', 'area_m2': intersection.area,
                'geometry': mapping(intersection), 'component_count': len(_parts(intersection)),
                'scope': 'Intersection of certified source floors; not an allocated or dimensioned service core.'}
    if not _parts(intersection):
        issues.append({'code': 'no_common_core_stacking_envelope', 'severity': 'requires_revision',
            'affected_outputs': ['geometry.mass', 'plan'], 'recommended_agents': ['mass', 'plan'],
            'requested_correction': 'Author a feasible vertical core strategy; these source floors have no common positive-area stacking envelope.'})
    return {'status': 'measured', 'door_access_verified': False,
            'scope': 'Polygon components and shared boundaries only; no assumed doors, stairs, corridor widths, or legal acceptance.',
            'stacking_envelope': envelope, 'floors': floor_reviews}, issues
