"""Area-aware recursive subdivision of gross reservations, not net rooms."""
from copy import deepcopy
import math

from shapely.geometry import Polygon, box, mapping
from shapely.ops import unary_union
from backend.app.modules.design.generation.services.connected_reservations import component_assignment


def _polygonal(geometry):
    if geometry.is_empty:
        return Polygon()
    if geometry.geom_type in ('Polygon', 'MultiPolygon'):
        return geometry
    if geometry.geom_type != 'GeometryCollection':
        return Polygon()
    parts = [_polygonal(part) for part in geometry.geoms]
    polygons = [part for part in parts if not part.is_empty]
    return unary_union(polygons) if polygons else Polygon()


def _split(geometry, fraction):
    minx, miny, maxx, maxy = geometry.bounds
    vertical = maxx - minx >= maxy - miny
    low, high = (minx, maxx) if vertical else (miny, maxy)
    target = geometry.area * fraction
    margin = max(maxx - minx, maxy - miny, 1.0)
    for _ in range(64):
        coordinate = (low + high) / 2
        cutter = (box(minx - margin, miny - margin, coordinate, maxy + margin) if vertical
                  else box(minx - margin, miny - margin, maxx + margin, coordinate))
        left = _polygonal(geometry.intersection(cutter))
        if left.area < target:
            low = coordinate
        else:
            high = coordinate
    return left, _polygonal(geometry.difference(left))


def _partition(geometry, rooms):
    if len(rooms) == 1:
        return [(rooms[0], geometry)]
    middle = len(rooms) // 2
    fraction = sum(room['area'] for room in rooms[:middle]) / sum(room['area'] for room in rooms)
    left, right = _split(geometry, fraction)
    return _partition(left, rooms[:middle]) + _partition(right, rooms[middle:])


def subdivide_gross_zones(footprint, rooms, options):
    from backend.app.modules.design.generation.services.floor_subdivision import _adjacency_bfs_order
    from backend.app.modules.design.generation.services.floor_packer import _ROOM_COLORS
    requested = sum(room['area'] for room in rooms)
    if not math.isclose(requested, footprint.area, rel_tol=1e-9, abs_tol=1e-6):
        raise ValueError('Gross reservation total must equal the measured floor footprint; no net-area conversion')
    count = options.get('num_variants', 1)
    if type(count) is not int or not 1 <= count <= 8:
        raise ValueError('num_variants must be an integer between 1 and 8 (runtime budget)')
    order = _adjacency_bfs_order(rooms)
    feasibility, groups = component_assignment(footprint, rooms)
    results = []
    for variant in range(count):
        offset = variant % len(order)
        ordering = order[offset:] + order[:offset]
        if variant >= len(order):
            ordering.reverse()
        if groups is not None and footprint.geom_type == 'MultiPolygon':
            partition = [row for part, group in zip(footprint.geoms, groups)
                         for row in _partition(part, [rooms[i] for i in ordering if i in group])]
        else:
            partition = _partition(footprint, [rooms[i] for i in ordering])
        geometries = {room['space_id']: geom for room, geom in partition}
        features, schedule = [], []
        for index, room in enumerate(rooms):
            geom = geometries[room['space_id']]
            if geom.is_empty or not geom.is_valid:
                raise ValueError('Gross subdivision produced invalid or missing reservation geometry')
            error = geom.area - room['area']
            provenance = {key: deepcopy(room[key]) for key in
                ('source_area', 'measurement_definition', 'area_status') if key in room}
            schedule.append({'space_id': room['space_id'], 'name': room['name'],
                'target_gross_m2': room['area'], 'actual_gross_m2': geom.area, 'error_m2': error,
                **deepcopy(provenance)})
            features.append({'type': 'Feature', 'geometry': mapping(geom), 'properties': {
                'space_id': room['space_id'], 'room_name': room['name'], 'room_code': index + 1,
                'area_basis': 'gross', 'area_m2': geom.area, 'target_gross_m2': room['area'],
                'source_refs': deepcopy(room.get('source_refs', [])),
                **deepcopy(provenance),
                'color': _ROOM_COLORS[(index + 1) % len(_ROOM_COLORS)],
                'disconnected': geom.geom_type == 'MultiPolygon'}})
        combined = unary_union(list(geometries.values()))
        results.append({'design_id': variant, 'floor_plan': {'type': 'FeatureCollection', 'features': features},
            'area_schedule': schedule, 'metrics': {'area_error': sum(abs(row['error_m2']) for row in schedule) / requested,
                'outside_m2': combined.difference(footprint).area,
                'unassigned_m2': footprint.difference(combined).area,
                'overlap_m2': sum(g.area for g in geometries.values()) - combined.area}})
    return {'algorithm': 'subdivision', 'num_results': len(results), 'results': results,
            'connectivity_feasibility': feasibility}
