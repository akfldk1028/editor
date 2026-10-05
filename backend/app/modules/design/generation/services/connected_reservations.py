"""Bounded whole-reservation assignment; no dimensional or legal rules."""
import math


def component_assignment(footprint, rooms):
    parts = [footprint] if footprint.geom_type == 'Polygon' else list(footprint.geoms)
    proof = {'method': 'whole_reservation_component_capacity',
             'component_areas_m2': [p.area for p in parts],
             'room_targets_m2': [r['area'] for r in rooms],
             'space_ids': [r['space_id'] for r in rooms],
             'scope': 'Necessary area-capacity condition for connected complete gross reservations; not occupancy qualification or access approval.'}
    if len(parts) == 1:
        return {**proof, 'status': 'not_disproved'}, [list(range(len(rooms)))]
    # 4096 subsets maximum, a computational budget rather than a design rule.
    if len(rooms) > 12:
        return {**proof, 'status': 'not_evaluated', 'reason': 'subset_runtime_budget'}, None
    subsets = [(mask, math.fsum(room['area'] for i, room in enumerate(rooms) if mask & (1 << i)))
               for mask in range(1, 1 << len(rooms))]
    matches = [[mask for mask, area in subsets if math.isclose(area, part.area, rel_tol=1e-9, abs_tol=1e-6)]
               for part in parts]
    missing = [i for i, choices in enumerate(matches) if not choices]
    if missing:
        return {**proof, 'status': 'impossible', 'unmatched_component_indices': missing}, None
    visited = set()
    def search(index, used):
        key = index, used
        if key in visited or len(visited) >= 4096:
            return None
        visited.add(key)
        if index == len(parts):
            return [] if used == (1 << len(rooms)) - 1 else None
        for mask in matches[index]:
            if mask & used:
                continue
            tail = search(index + 1, used | mask)
            if tail is not None:
                return [mask, *tail]
        return None
    assignment = search(0, 0)
    if assignment is None:
        return {**proof, 'status': 'not_disproved', 'reason': 'no_assignment_within_search_budget'}, None
    groups = [[i for i in range(len(rooms)) if mask & (1 << i)] for mask in assignment]
    return {**proof, 'status': 'capacity_assignment_found',
            'component_space_ids': [[rooms[i]['space_id'] for i in group] for group in groups]}, groups


def reject_fragmented(result):
    from shapely.geometry import shape
    accepted, rejected = [], []
    for variant in result['results']:
        fragments = {}
        for feature in variant['floor_plan']['features']:
            geometry = shape(feature['geometry'])
            if geometry.geom_type == 'MultiPolygon' and len(geometry.geoms) > 1:
                fragments[feature['properties']['space_id']] = [part.area for part in geometry.geoms]
        if fragments:
            variant['candidate_status'] = 'rejected'
            variant['rejection'] = {'code': 'fragmented_gross_reservations',
                'space_ids': list(fragments), 'component_areas_m2': fragments}
            variant['floor_plan']['candidate_status'] = 'rejected'
            variant['floor_plan']['rejection'] = variant['rejection']
            rejected.append(variant)
        else:
            variant['candidate_status'] = 'connected_gross_proposal'
            accepted.append(variant)
    return {**result, 'results': accepted, 'num_results': len(accepted),
            'rejected_candidates': rejected,
            'generation_status': 'candidates_available' if accepted else 'needs_revision'}
