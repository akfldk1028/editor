"""Construction-derived envelope with closed-lift structural piers excluded.

This deliberately supports only fixed affine CSG and the authoritative lift
constructor. Unknown macros are not silently qualified as occupiable capacity.
"""
from hashlib import sha256
import json
from pathlib import Path


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def compile_occupied_envelope(document):
    from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryProgram
    from backend.app.modules.design.generation.maas.geometry_language.compiler import _evaluate_node, normalize_unitbox_program
    from backend.app.modules.design.generation.maas.geometry_language.lift_parts import lift_parts
    from backend.app.modules.design.generation.maas.geometry_language import compiler, lift_parts as constructor
    import manifold3d as m3d
    program = normalize_unitbox_program(GeometryProgram.from_dict(document))
    if any(issue.severity == 'error' for issue in program.validate()):
        raise ValueError('invalid source geometry program')
    node_map, cache, exclusions = program.node_map, {}, []
    allowed = {('primitive', 'box'), ('transform', 'matrix4'),
               ('boolean', 'union'), ('boolean', 'intersection'), ('boolean', 'difference'), ('macro', 'lift')}
    for node in program.nodes:
        if ((node.kind, node.operator) not in allowed
                or (node.provenance or {}).get('book_verb') == 'recompose_book_scope'):
            raise ValueError('unsupported occupied-envelope operator: ' + node.id)
    def evaluate(node_id):
        if node_id in cache:
            return cache[node_id]
        node = node_map[node_id]
        pairs = [evaluate(key) for key in node.inputs]
        full_inputs, occupied_inputs = [p[0] for p in pairs], [p[1] for p in pairs]
        full, _ = _evaluate_node(node, full_inputs, node_map=node_map)
        if node.operator == 'lift':
            _, supports, expansion, rise = lift_parts(full_inputs[0], node.parameters)
            occupied = occupied_inputs[0].translate((0, 0, rise))
            if 'access_bound_service_spine' in expansion:
                occupied = m3d.Manifold.batch_boolean([occupied, *supports], m3d.OpType.Add)
            else:
                exclusions.append({'node_id': node.id, 'semantic_role': node.semantic_role,
                    'support_role': 'structural_support_array', 'constructor': 'lift_parts',
                    'access_side': str(node.parameters.get('access_side') or 'closed').lower(),
                    'support_count': len(supports), 'rise_m_in_node_coordinates': rise})
        else:
            # Boolean cutters retain physical geometry; they are not occupied rooms.
            if node.kind == 'boolean' and node.operator == 'difference':
                occupied_inputs = occupied_inputs[:1] + full_inputs[1:]
            occupied, _ = _evaluate_node(node, occupied_inputs, node_map=node_map)
        cache[node_id] = full, occupied
        return full, occupied
    full, occupied = evaluate(program.root_id)
    return full, occupied, {'schema': 'arr.constructor_occupied_envelope.v1',
        'capacity_basis': 'constructor_occupied_envelope', 'source_program_hash': _digest(document),
        'support_exclusions': exclusions,
        'owner_code_hashes': {path.name: sha256(path.read_bytes()).hexdigest()
                              for path in (Path(compiler.__file__), Path(constructor.__file__), Path(__file__))},
        'scope': 'Building-envelope CSG excluding constructor-tagged closed-lift structural supports; not usable net area, statutory floor area, structural approval or egress proof.'}


def aligned_envelopes(document, evidence):
    full, occupied, semantic = compile_occupied_envelope(document)
    matrix = [list(row) for row in evidence['normalized_host_fit_matrix4']]
    z_scale = float(evidence['z_scale'])
    if not matrix[2][2]:
        raise ValueError('missing exact delivered Z transform')
    height = z_scale / float(matrix[2][2])
    matrix[2] = [value * height for value in matrix[2]]
    semantic['physical_matrix4'] = matrix
    return full.transform(matrix[:3]), occupied.transform(matrix[:3]), semantic
