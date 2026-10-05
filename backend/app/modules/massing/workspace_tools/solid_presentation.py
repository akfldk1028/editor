"""Presentation-only equality of complete occupied, uniformly normalized solids.

This never changes source shape IDs, certificates, scores or source records.
The normalized ground plane remains significant: a sunken or raised body
is not equivalent to the same isolated shape standing on grade.
Typed bodies use the source owner's sampled columns; BOOK uses its complete
authoritative mesh. Unsupported conversion keeps a choice separate.
"""
from __future__ import annotations

from backend.app.modules.massing import paths as _mass_paths
from backend.app.modules.design.generation import paths as _design_paths
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime


from dataclasses import dataclass
import hashlib
import json
from math import isfinite

import manifold3d as m3d

from backend.app.modules.design.generation.maas.geometry_language.export_mesh import EXPORT_DECIMAL_PLACES
from backend.app.modules.design.generation.maas.geometry_language.source_bridge import mesh_section_solid
from backend.app.modules.design.generation.maas.massv2.render_mesh import is_mesh_authoritative, physical_triangles
from backend.app.modules.design.generation.maas.source_geometry.ir import SourceMass


POLICY = 'translation_uniform_xyz'
EQUALITY = 'both_closed_boolean_differences_empty_and_same_ground_relation'


@dataclass(frozen=True)
class _Prepared:
    solid: object
    key: str
    proof: dict


def _valid(solid, *, allow_empty=False):
    if solid.status() != m3d.Error.NoError:
        raise ValueError(f'invalid closed solid: {solid.status()}')
    if not allow_empty and (solid.is_empty() or not isfinite(solid.volume()) or solid.volume() <= 0):
        raise ValueError('positive closed occupied solid required')
    return solid


def _column_solid(volume, height):
    """Close shared sampled top/bottom triangles and their boundary walls."""
    low, high = volume.bottom_fraction * height, volume.top_fraction * height
    if not all(isfinite(v) for v in (low, high)) or high <= low:
        raise ValueError('positive finite volume band required')
    vertices, faces, lookup, edges = [], [], {}, {}

    def point_id(point):
        point = tuple(float(v) for v in point)
        if not all(isfinite(v) for v in point):
            raise ValueError('nonfinite shared surface vertex')
        if point not in lookup:
            lookup[point] = len(vertices)
            vertices.append(point)
        return lookup[point]

    def face(points):
        if len(set(points)) == 3:
            faces.append(tuple(points))

    for raw in volume.surface_mesh:
        a, b, c = raw
        if any(bottom > top for _, _, bottom, top in raw):
            raise ValueError('inverted sampled occupied interval')
        if (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0]) < 0:
            raw = (a, c, b)
        bottom = [point_id((x, y, low+(high-low)*z)) for x, y, z, _ in raw]
        top = [point_id((x, y, low+(high-low)*z)) for x, y, _, z in raw]
        face(top)
        face(tuple(reversed(bottom)))
        for i in range(3):
            j = (i+1) % 3
            key = tuple(sorted((bottom[i], bottom[j])))
            edges.setdefault(key, []).append((bottom[i], bottom[j], top[i], top[j]))
    for incident in edges.values():
        if len(incident) == 1:
            a, b, at, bt = incident[0]
            face((a, b, bt))
            face((a, bt, at))
        elif len(incident) != 2:
            raise ValueError('shared plan has a non-manifold edge')
    if not faces:
        raise ValueError('shared surface has no occupied faces')
    return _valid(mesh_section_solid(vertices, faces))


def _prepare(source):
    if not isinstance(source, SourceMass):
        raise ValueError('SourceMass with complete geometry authority required')
    if is_mesh_authoritative(source):
        triangles = physical_triangles(source)
        vertices = [point for triangle in triangles for point in triangle]
        faces = [(i, i+1, i+2) for i in range(0, len(vertices), 3)]
        solid = _valid(mesh_section_solid(vertices, faces))
        authority = 'authoritative_book_physical_triangles'
    else:
        height = float((source.metadata or {}).get('authored_height_m') or 0)
        if not isfinite(height) or height <= 0 or not source.volumes:
            raise ValueError('typed source requires occupied volumes and physical height')
        parts = [_column_solid(volume, height) for volume in source.volumes]
        solid = _valid(m3d.Manifold.batch_boolean(parts, m3d.OpType.Add))
        authority = 'shared_source_volume_surface_mesh_union'
    bounds = tuple(float(v) for v in solid.bounding_box())
    extents = tuple(bounds[i+3]-bounds[i] for i in range(3))
    if not all(isfinite(v) for v in bounds) or min(extents) <= 0:
        raise ValueError('finite three-dimensional occupied bounds required')
    ruler = max(extents)
    datum = float((source.metadata or {}).get('datum_m') or 0)
    if not isfinite(datum):
        raise ValueError('finite ground datum required')
    normalized_ground = (datum - bounds[2]) / ruler
    normalized = _valid(solid.translate(tuple(-v for v in bounds[:3])).scale((1/ruler,)*3))
    # Existing export precision is ONLY a candidate-bucket key, not a vertex
    # snap or a geometric equality tolerance. Both differences still must be
    # valid kernel results and completely empty before any alias is admitted.
    signature = [round(v/ruler, EXPORT_DECIMAL_PLACES) for v in extents]
    signature.append(round(normalized_ground, EXPORT_DECIMAL_PLACES))
    key = hashlib.sha256(json.dumps(signature).encode()).hexdigest()[:20]
    proof = {'authority': authority, 'closed_kernel_solid': True,
        'normalization': {'policy': POLICY, 'original_bounds': list(bounds),
            'translation_xyz': [-v for v in bounds[:3]], 'uniform_xyz_scale': 1/ruler,
            'normalized_bounds': list(normalized.bounding_box()),
            'normalized_ground_z': normalized_ground,
            'ground_relation_preserved': True,
            'rotation_or_axis_stretch': False},
        'bucket_key': key, 'bucket_signature': signature,
        'bucket_precision': EXPORT_DECIMAL_PLACES,
        'normalized_volume': float(normalized.volume()),
        'sampled_geometry_not_analytic_error_certificate': True}
    return _Prepared(normalized, key, proof)


def _compare(a, b):
    a_minus_b = _valid(m3d.Manifold.batch_boolean([a.solid, b.solid], m3d.OpType.Subtract), allow_empty=True)
    b_minus_a = _valid(m3d.Manifold.batch_boolean([b.solid, a.solid], m3d.OpType.Subtract), allow_empty=True)
    return {'a_minus_b_empty': bool(a_minus_b.is_empty()),
            'b_minus_a_empty': bool(b_minus_a.is_empty()),
            'normalized_ground_equal': a.proof['normalization']['normalized_ground_z'] ==
                                       b.proof['normalization']['normalized_ground_z'],
            'a_minus_b_volume': float(a_minus_b.volume()),
            'b_minus_a_volume': float(b_minus_a.volume()),
            'valid_closed_difference_results': True}


class SolidPresentationRegistry:
    """One cached solid per representative; callers retain every original row."""
    def __init__(self):
        self._buckets = {}

    def find_or_add(self, name, source):
        try:
            candidate = _prepare(source)
            checked = []
            for other_name, other in self._buckets.get(candidate.key, ()):
                comparison = _compare(other, candidate)
                checked.append({'name': other_name, **comparison})
                if (comparison['a_minus_b_empty'] and comparison['b_minus_a_empty']
                        and comparison['normalized_ground_equal']):
                    return {'duplicate_of': other_name, 'status': 'verified', 'proof': {
                        **candidate.proof, **comparison, 'representative': other.proof,
                        'comparison_policy': EQUALITY}}
            self._buckets.setdefault(candidate.key, []).append((name, candidate))
            return {'duplicate_of': None, 'status': 'verified', 'proof': {
                **candidate.proof, 'comparisons': checked,
                'comparison_policy': EQUALITY}}
        except (ValueError, TypeError, AttributeError, OverflowError, RuntimeError) as error:
            return {'duplicate_of': None, 'status': 'unsupported', 'proof': {
                'normalization': {'policy': POLICY},
                'reason': f'{type(error).__name__}: {error}',
                'choice_must_remain_separate': True}}
