"""Pure support measurements from complete physical export triangles.

This module is deliberately unconnected to production standing judgements.
Uniform solid density, connected material and support hulls are geometric
screening evidence, not strength, anchorage or structural design approval.
No structural acceptance thresholds are defined here.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from hashlib import sha256
import json
from math import fsum, isfinite

import numpy as np
from shapely.geometry import Point, Polygon, mapping
from shapely.ops import unary_union

from backend.app.modules.design.generation.maas.massv2.render_mesh import physical_triangles


def _canonical(triangles):
    # Preserve winding and all coordinate precision; only reorder traversal.
    return tuple(sorted(min(tuple(t[i:])+tuple(t[:i]) for i in range(3))
                        for t in (tuple(tuple(float(v) for v in p) for p in t) for t in triangles)))


def _triangles(solid):
    mesh = solid.to_mesh64()
    points = np.asarray(mesh.vert_properties)[:, :3]
    return _canonical(tuple(tuple(points[i]) for i in face) for face in mesh.tri_verts)


def _moments(triangles):
    t = np.asarray(triangles, dtype=float)
    origin = (t.min(axis=(0, 1))+t.max(axis=(0, 1)))/2
    q = t-origin
    volumes = np.einsum('ij,ij->i', q[:, 0], np.cross(q[:, 1], q[:, 2]))/6
    volume = fsum(float(v) for v in volumes)
    if volume <= 0 or not isfinite(volume):
        raise ValueError('positive oriented material volume required')
    moments = (q.sum(axis=1)/4)*volumes[:, None]
    com = [float(origin[i]+fsum(float(v) for v in moments[:, i])/volume) for i in range(3)]
    return volume, com


def _solid(triangles):
    from backend.app.modules.design.generation.maas.geometry_language.source_bridge import mesh_section_solid
    vertices = [p for triangle in triangles for p in triangle]
    return mesh_section_solid(vertices, [(i, i+1, i+2) for i in range(0, len(vertices), 3)])


def _material_bodies(solid, volume_resolution):
    """Group inner cavity shells with their containing material component.

    Manifold.decompose returns boundary shells, including negative-volume
    enclosed voids. Treating those as floating bodies would be incorrect.
    """
    shells = list(solid.decompose())
    bodies = [s for s in shells if s.volume() > volume_resolution]
    voids = [s for s in shells if s.volume() < -volume_resolution]
    remnants = sum(bool(abs(s.volume()) <= volume_resolution) for s in shells)
    for shell in voids:
        void = _solid(tuple((t[0], t[2], t[1]) for t in _triangles(shell)))
        owners = [i for i, body in enumerate(bodies)
                  if abs((body ^ void).volume()-void.volume()) <= volume_resolution]
        if not owners:
            raise ValueError('oriented cavity has no enclosing material component')
        owner = min(owners, key=lambda i: bodies[i].volume())
        bodies[owner] = bodies[owner]-void
    return sorted(bodies, key=lambda s: tuple(s.bounding_box()) + (s.volume(),)), remnants


def _plane_faces(solid, z, length_resolution, *, upward):
    faces = []
    for t in _triangles(solid):
        if all(abs(p[2]-z) <= length_resolution for p in t):
            cross = np.cross(np.asarray(t[1])-t[0], np.asarray(t[2])-t[0])[2]
            if (cross > 0) == upward and cross != 0:
                polygon = Polygon([(p[0], p[1]) for p in t])
                if polygon.area > 0:
                    faces.append(polygon)
    return unary_union(faces) if faces else Polygon()


def _region_evidence(region):
    polygons = [region] if region.geom_type == 'Polygon' else [p for p in getattr(region, 'geoms', ()) if p.geom_type == 'Polygon']
    polygons = [p for p in polygons if not p.is_empty and p.area > 0]
    return {'area_m2': float(region.area), 'patch_count': len(polygons),
            'hole_count': sum(len(p.interiors) for p in polygons),
            'hull_area_m2': float(region.convex_hull.area),
            'geometry_xy_m': mapping(region)}


def _margin(contact, com):
    if contact.is_empty or contact.area <= 0:
        return None
    hull, point = contact.convex_hull, Point(com[:2])
    distance = float(hull.boundary.distance(point))
    return distance if hull.covers(point) else -distance


def measure_mesh_support(source, *, datum_m=None, critical_heights=True):
    """Return JSON evidence; refuse incomplete, open or misoriented meshes.

    Every material component answers for its own ground contact. At each
    interior vertex height and each interval midpoint, split the *actual*
    solid and intersect upper-body bottom caps with lower-solid top caps.
    These event/probe measurements do not establish a continuous all-height
    extremum, nor egress between bodies. Datum is a plane, never a Z offset.
    """
    triangles = _canonical(physical_triangles(source))
    datum = float(source.metadata.get('datum_m', 0) if datum_m is None else datum_m)
    if not isfinite(datum):
        raise ValueError('finite ground datum required')
    edges = defaultdict(list)
    vertices = set()
    for triangle in triangles:
        vertices.update(triangle)
        for a, b in zip(triangle, triangle[1:]+triangle[:1]):
            if a == b:
                raise ValueError('closed oriented mesh requires nondegenerate edges')
            edges[tuple(sorted((a, b)))].append((a, b))
    if any(len(v) != 2 or v[0] != tuple(reversed(v[1])) for v in edges.values()):
        raise ValueError('closed consistently oriented mesh required')
    solid = _solid(triangles)
    points = np.asarray(tuple(vertices))
    span = max(1., float(np.ptp(points, axis=0).max()))
    # Arithmetic resolution only: 64 floating-point ulps at coordinate scale.
    # Never use the structure owner's 5 cm band tolerance to weld real gaps.
    length_resolution = float(64*np.finfo(float).eps*max(1., float(np.abs(points).max())))
    volume_resolution = length_resolution*span*span
    bodies, discarded = _material_bodies(solid, volume_resolution)
    if not bodies or discarded:
        raise ValueError('original mesh contains numerically unresolved material components')
    volume, com = _moments(triangles)
    components, contacts = [], []
    for i, body in enumerate(bodies):
        body_volume, body_com = _moments(_triangles(body))
        upper = body.trim_by_plane((0, 0, 1), datum)
        contact = _plane_faces(upper, datum, length_resolution, upward=False) if not upper.is_empty() else Polygon()
        contacts.append(contact)
        components.append({'component_index': i, 'volume_m3': body_volume,
            'uniform_density_com_xyz_m': body_com, 'bounds_xyz_m': list(body.bounding_box()),
            'ground_contact': _region_evidence(contact), 'has_ground_contact': contact.area > 0,
            'ground_margin_m': _margin(contact, body_com),
            'com_height_above_ground_m': body_com[2]-datum})
    sections = []
    if critical_heights:
        levels = sorted({float(p[2]) for p in vertices} | {datum})
        levels = [z for z in levels if datum <= z <= points[:, 2].max()]
        if len(levels) > 40:
            step = (levels[-1] - levels[0]) / 40.0
            clustered = [levels[0]]
            for z in levels[1:-1]:
                if z - clustered[-1] >= step:
                    clustered.append(z)
            clustered.append(levels[-1])
            levels = clustered
        events = [(z, 'vertex_height') for z in levels[1:-1]]
        probes = [((a+b)/2, 'interval_midpoint') for a, b in zip(levels, levels[1:])
                  if b-a > 2*length_resolution]
        for z, kind in sorted(events+probes):
            upper, lower = solid.split_by_plane((0, 0, 1), z)
            upper_bodies, remnants = _material_bodies(upper, volume_resolution)
            lower_cap = _plane_faces(lower, z, length_resolution, upward=True) if not lower.is_empty() else Polygon()
            rows = []
            for i, body in enumerate(upper_bodies):
                body_volume, body_com = _moments(_triangles(body))
                cap = _plane_faces(body, z, length_resolution, upward=False)
                bearing = cap.intersection(lower_cap)
                rows.append({'upper_component_index': i, 'volume_m3': body_volume,
                    'uniform_density_com_xyz_m': body_com, 'bounds_xyz_m': list(body.bounding_box()),
                    'base_area_m2': float(cap.area), 'bearing': _region_evidence(bearing),
                    'has_bearing': bearing.area > 0, 'support_margin_m': _margin(bearing, body_com),
                    'com_height_above_cut_m': body_com[2]-z})
            sections.append({'height_m': z, 'sample_kind': kind, 'upper_component_count': len(rows),
                             'numerical_split_remnants': remnants, 'upper_components': rows})
    margins = [c['ground_margin_m'] for c in components if c['ground_margin_m'] is not None]
    critical_margins = [b['support_margin_m'] for s in sections for b in s['upper_components'] if b['support_margin_m'] is not None]
    observations = []
    if any(not c['has_ground_contact'] for c in components):
        observations.append('component_without_ground_contact')
    if any(m <= 0 for m in margins):
        observations.append('component_com_not_strictly_inside_ground_hull')
    if any(not b['has_bearing'] for s in sections for b in s['upper_components']):
        observations.append('upper_component_without_bearing_at_sample')
    if any(m <= 0 for m in critical_margins):
        observations.append('upper_component_com_not_strictly_inside_bearing_hull_at_sample')
    return {'schema_version': 'arr.maas.mesh_support_measurement.v1',
        'coordinate_authority': 'backend.app.modules.design.generation.maas.massv2.render_mesh.physical_triangles',
        'mesh_sha256': sha256(json.dumps(triangles, separators=(',', ':'), allow_nan=False).encode()).hexdigest(),
        'datum_m': datum, 'mass_model': 'uniform_solid_density',
        'closed_oriented_mesh': True, 'triangle_count': len(triangles), 'vertex_count': len(vertices),
        'edge_incidence_counts': dict(sorted(Counter(len(v) for v in edges.values()).items())),
        'kernel_status': str(solid.status()), 'component_count': len(components),
        'volume_m3': volume, 'uniform_density_com_xyz_m': com,
        'ground_contact_area_m2': float(unary_union(contacts).area),
        'grounded_volume_share': fsum(c['volume_m3'] for c in components if c['has_ground_contact'])/volume,
        'minimum_ground_margin_m': min(margins) if margins else None,
        'components': components, 'critical_heights_evaluated': bool(critical_heights),
        'critical_sections': sections,
        'minimum_critical_margin_m': min(critical_margins) if critical_margins else None,
        'numerical_resolution': {'length_m': length_resolution, 'volume_m3': volume_resolution,
                                 'basis': '64 binary64 ulps at coordinate scale; no geometry snapping'},
        'observations': observations,
        'limitations': ['Geometric support screening, not structural design or anchorage approval.',
                        'A negative upper-body margin identifies moment-transfer demand; it is not alone a structural refusal.',
                        'Critical vertex heights and interval midpoints are samples, not continuous extrema.',
                        'Ground datum is supplied; no terrain or geotechnical measurement is inferred.',
                        'No standing decision, member span/backspan threshold or production gate is applied.']}
