"""Tracked BOOK delivery helper extracted unchanged from the legacy owner tools.

No registry discovery, jury scheduling, or runtime CLI import belongs here.
"""
from shapely.geometry import Polygon


def delivered_floor_evidence(source, storeys, *, floor_count, storey_m):
    """Measure the exported mesh at the executed authored floor centers.

    Host fitting controls XY independently of requested stature. Its exact
    affine map is the transport authority; a height ratio is not an area scale.
    The volume bands remain conservative occupancy proxies, not floor areas.
    """
    from math import isfinite
    from shapely.ops import unary_union
    from backend.app.modules.design.generation.maas.geometry_language.source_bridge import mesh_section_solid, solid_section_polygon, _mesh_plan_projection_area, section_export_area_resolution, _compile_geometry_program_cached, section_coplanar_skin_area
    bridge = source.metadata['geometry_program_bridge_evidence']
    matrix = bridge['host_fit_matrix4']
    if not bridge.get('host_fit_matrix4_exact') or any(
            matrix[i][j] != 0 for i, j in ((0, 2), (1, 2), (2, 0), (2, 1))):
        raise ValueError('BOOK floor schedule requires an exact horizontal affine placement')
    count = int(floor_count)
    original_centers = storeys.get('floor_center_elevations_m')
    center_basis = 'authored_floor_center_elevations_m'
    if original_centers is None:
        original_centers = [(i + .5) * float(storey_m) for i in range(count)]
        center_basis = 'authored_count_and_typical_storey_height'
    centers = [float(z) for z in original_centers]
    if len(centers) != count or any(not isfinite(z) for z in centers) or any(
            a >= b for a, b in zip(centers, centers[1:])):
        raise ValueError('invalid authored BOOK floor-center schedule')
    fractions = [matrix[2][2] * z + matrix[2][3] for z in centers]
    if any(not 0 < z < 1 for z in fractions):
        raise ValueError('authored BOOK floor center outside delivered solid height')
    vertices = tuple(p for s in source.surfaces for p in s.vertices_m)
    triangles = tuple((i, i+1, i+2) for i in range(0, len(vertices), 3))
    if not vertices or any(len(s.vertices_m) != 3 for s in source.surfaces):
        raise ValueError('BOOK requires a complete triangle mesh')
    # A horizontal skin exactly at a floor's centre plane makes the section
    # there a coin toss, and the rule below refused it. The book's joints sit
    # at half height, and half of 5 x 3.8 m is floor 3's centre, so comp23
    # refused every vertical sentence for it. The probe steps off the skin by
    # 2% of a storey to the side with the smaller section - the conservative
    # floor - and the offset is recorded.
    probe_offsets = [0.0] * len(fractions)
    if storey_m:
        step = abs(float(matrix[2][2])) * 0.02 * float(storey_m)
        probe = mesh_section_solid(vertices, triangles)
        for index, z in enumerate(list(fractions)):
            if section_coplanar_skin_area(vertices, triangles, z, matrix) <= 0.0:
                continue
            below, above = z - step, z + step
            if not (0 < below and above < 1):
                continue
            candidates = []
            for side in (below, above):
                polygon = solid_section_polygon(probe, side)
                candidates.append((float(polygon.area) if polygon is not None else 0.0, side))
            area, side = min(candidates)
            fractions[index] = side
            probe_offsets[index] = side - z
    solid = mesh_section_solid(vertices, triangles)
    sections = [solid_section_polygon(solid, z) for z in fractions]
    empty_floors = [index for index, p in enumerate(sections) if p is None or p.is_empty or p.area <= 0]
    if empty_floors and not source.metadata.get('legal_host_clip'):
        raise ValueError('authored BOOK floor has no delivered occupied section')
    # Under a cut, a floor with no section is either the law's whole take
    # of that floor (its legal section had no room where the authored floor
    # stood) or a pose that missed the parcel; the first is recorded below
    # and the second still refuses.
    removed_by_law: set[int] = set(empty_floors)
    from shapely.geometry import Polygon as _Empty
    sections = [p if index not in removed_by_law else _Empty() for index, p in enumerate(sections)]
    areas = [float(p.area) for p in sections]
    height = float(source.metadata['authored_height_m'])
    origin = source.footprint.centroid
    from shapely.affinity import translate
    proxy_areas, missing_areas = [], []
    for z, section in zip(fractions, sections):
        proxy = unary_union([v.footprint for v in source.volumes
                             if v.bottom_fraction <= z <= v.top_fraction])
        proxy_areas.append(float(proxy.area))
        missing_areas.append(float(translate(section, xoff=origin.x, yoff=origin.y).difference(proxy).area))
    from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryProgram
    original = _compile_geometry_program_cached(GeometryProgram.from_dict(source.metadata['geometry_program']))
    physical_matrix = [list(row) for row in matrix]
    physical_matrix[2] = [value * height for value in physical_matrix[2]]
    transformed = original._solid.transform(physical_matrix[:3])
    # Delivered through a cut: the reference is the authored floor inside
    # the host the bridge cut at, not the whole authored floor. The
    # difference is the law's take, recorded per floor.
    clip = source.metadata.get('legal_host_clip')
    clip_host = None
    clip_bands = []
    if isinstance(clip, dict) and clip.get('exterior'):
        clip_host = Polygon([tuple(pt) for pt in clip['exterior']],
                            [[tuple(pt) for pt in hole] for hole in clip.get('holes') or ()])
        clip_bands = [(float(b['lo']), float(b['hi']),
                       Polygon([tuple(pt) for pt in b['exterior']],
                               [[tuple(pt) for pt in hole] for hole in b.get('holes') or ()]))
                      for b in clip.get('sections') or ()]
    def host_at(z):
        for lo, hi, poly in clip_bands:
            if lo - 1e-9 <= z < hi + 1e-9:
                return poly
        return clip_host
    original_areas, legal_take_areas = [], []
    for z in fractions:
        section = transformed.slice(z * height)
        if clip_host is None:
            original_areas.append(float(section.area()))
            legal_take_areas.append(0.0)
            continue
        region = None
        for contour in section.to_polygons():
            ring = Polygon(contour)
            if ring.is_empty or ring.area <= 0:
                continue
            region = ring if region is None else region.symmetric_difference(ring)
        whole = float(region.area) if region is not None else 0.0
        inside = float(region.intersection(host_at(z)).area) if region is not None else 0.0
        floor_index = len(original_areas)
        if floor_index in removed_by_law:
            if inside > 1.0:
                # The law left room for this floor and the delivery has none there.
                raise ValueError('authored BOOK floor has no delivered occupied section')
            inside = 0.0
        original_areas.append(inside)
        legal_take_areas.append(whole - inside)
    resolutions = [section_export_area_resolution(p, matrix) for p in sections]
    coplanar_areas = [section_coplanar_skin_area(vertices, triangles, z, matrix) for z in fractions]
    area_scale = abs(matrix[0][0]*matrix[1][1] - matrix[0][1]*matrix[1][0])
    authored_areas = storeys.get('actual_floor_areas_m2')
    if authored_areas is not None and len(authored_areas) != count:
        raise ValueError('authored BOOK floor-area schedule count mismatch')
    transported_areas = [float(a) * area_scale for a in authored_areas] if authored_areas is not None else None
    # A published decimal floor schedule has its own last-place rounding.
    # Derive that resolution from the supplied values, not another hardcoded
    # geometry tolerance or a duplicate of the portfolio writer's precision.
    from decimal import Decimal
    authored_resolutions = [resolution + .5 * 10.0 ** Decimal(str(a)).as_tuple().exponent * area_scale
                            for a, resolution in zip(authored_areas, resolutions)] if authored_areas is not None else None
    issues = []
    for index, (actual, reference, missing, resolution) in enumerate(zip(
            areas, original_areas, missing_areas, resolutions), 1):
        if abs(actual - reference) > resolution:
            issues.append(f'floor_{index}_original_export_area_mismatch:{reference:.9f}->{actual:.9f}')
        if missing > resolution:
            issues.append(f'floor_{index}_mesh_area_missing_from_proxy:{missing:.9f}')
        if coplanar_areas[index-1] > resolution:
            issues.append(f'floor_{index}_ambiguous_horizontal_skin_at_center:{coplanar_areas[index-1]:.9f}')
        if transported_areas is not None and clip_host is None and (
                not isfinite(transported_areas[index-1])
                or abs(actual - transported_areas[index-1]) > authored_resolutions[index-1]):
            issues.append(f'floor_{index}_authored_export_area_mismatch:{transported_areas[index-1]:.9f}->{actual:.9f}')
    from backend.app.modules.design.generation.maas.delivered.book_identity import shape_id
    return {
        'schema': 'arr.maas.book_delivered_floor_measurement.v1',
        'basis': 'delivered SourceSurface mesh at transformed authored floor centers',
        'legal_clip': clip_host is not None,
        'legal_take_areas_m2': [round(a, 6) for a in legal_take_areas],
        'floors_removed_by_law': sorted(index + 1 for index in removed_by_law),
        'placement_policy': 'host-fitted XY affine; independently requested Z stature',
        'center_basis': center_basis,
        'original_floor_center_elevations_m': centers,
        'delivered_floor_center_elevations_m': [z * height for z in fractions],
        'actual_floor_areas_m2': areas,
        'actual_gfa_m2': sum(areas),
        'source_shape_id': shape_id(source),
        'original_transformed_floor_areas_m2': original_areas,
        'authored_floor_areas_at_executed_xy_m2': transported_areas,
        'authored_floor_area_comparison_resolution_m2': authored_resolutions,
        'coplanar_skin_area_at_floor_center_m2': coplanar_areas,
        # Only when a probe moved: the key would change every earlier
        # seat's certificate otherwise (comp23's sheet ghosted all of them).
        **({'floor_center_probe_offsets': probe_offsets} if any(probe_offsets) else {}),
        'export_area_comparison_resolution_m2': resolutions,
        'measurement_consistent': not issues,
        'measurement_issues': issues,
        'mesh_projection_m2': _mesh_plan_projection_area(vertices, triangles),
        'proxy_floor_areas_m2': proxy_areas,
        'mesh_floor_area_missing_from_proxy_m2': missing_areas,
        'xy_area_scale': area_scale,
        'z_scale': matrix[2][2] * height,
        'normalized_host_fit_matrix4': matrix,
        'requested_plan_area_m2': bridge.get('effective_target_plan_area'),
        'plan_area_target_satisfied': bridge.get('minimum_plan_area_target_satisfied'),
        'plan_area_shortfall_ratio': bridge.get('minimum_plan_area_shortfall_ratio'),
    }
