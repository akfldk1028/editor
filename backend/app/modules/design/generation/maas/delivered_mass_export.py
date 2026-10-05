"""Export the exact completed Mass cycle champion; never replay a pre-fit mesh."""

from backend.app.modules.design.generation import paths as _design_paths
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import tempfile


BACKEND = _design_paths.backend_root()
DEFAULT_WORKSPACE = BACKEND / 'tmp_mass_check/_massv2'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _inside(path, root):
    path = Path(path).resolve(strict=True)
    if not path.is_relative_to(root):
        raise ValueError('source evidence is outside its configured workspace')
    return path


def selected_source(request, roots):
    raw = Path(request['completion_path'])
    if not raw.is_absolute():
        raise ValueError('completion_path must be absolute')
    completion = raw.resolve(strict=True)
    roots = [Path(root).resolve(strict=True) for root in roots]
    matches = [root for root in roots if completion.is_relative_to(root)]
    if len(matches) != 1:
        raise ValueError('completion workspace must be explicitly configured')
    workspace = matches[0]
    source_roots = [Path(root).resolve() for root in json.loads(os.environ.get(
        'EDITOR_MASS_SOURCE_ROOTS', json.dumps([os.environ.get('EDITOR_MASS_OUTPUT_ROOT', str(BACKEND / 'tmp_mass_check')), *[str(root) for root in roots]])))]
    if (completion.name != 'complete.json' or completion.parent.parent != workspace / 'runs'
            or not completion.parent.name.startswith('cycle-')):
        raise ValueError('completion must name a cycle receipt')
    if file_hash(completion) != request['completion_sha256']:
        raise ValueError('completion receipt hash mismatch')
    state_path = completion.with_name('state.json')
    state_hash = file_hash(state_path)
    state, receipt = read(state_path), read(completion)
    config = state['config']
    if (state['status'] != 'complete' or receipt['status'] != 'complete'
            or receipt['round'] != config['round']
            or completion.parent.name != 'cycle-' + config['round']):
        raise ValueError('cycle is not complete')
    identity = request['source_identity']
    if any(identity.get(key) != config.get(key) for key in ('pnu', 'building_type')):
        raise ValueError('completed cycle parcel or building type differs from request')
    champion = receipt['feedback']['champion']
    if not isinstance(champion, str) or not champion.startswith('book:'):
        raise ValueError('a delivered BOOK champion is required')
    evidence = {str(completion): request['completion_sha256'], str(state_path): state_hash}
    outputs = {}
    for action in state['actions'].values():
        for path, expected in action.get('outputs', {}).items():
            resolved = Path(path).resolve()
            if resolved in outputs and outputs[resolved] != expected:
                raise ValueError('conflicting cycle artifact receipts')
            outputs[resolved] = expected
    if outputs.get(completion) != request['completion_sha256']:
        raise ValueError('completion is not pinned by the cycle')
    entries = []
    for path, expected in outputs.items():
        if path.parent != workspace / 'runs/books' or path.suffix != '.json':
            continue
        path = _inside(path, workspace)
        if file_hash(path) != expected:
            raise ValueError('completed BOOK registry changed')
        evidence[str(path)] = expected
        data = read(path)
        entry = (data.get('entries') or {}).get(champion)
        if entry:
            book_dir = Path(data['book_dir']).resolve(strict=True)
            if not any(book_dir.is_relative_to(root) for root in source_roots):
                raise ValueError('geometry source directory must be explicitly configured')
            entries.append({**entry, 'book_dir': str(book_dir)})
    identities = {(e.get('delivered_shape_id'), (e.get('numeric_certificate') or {}).get('certificate_id'))
                  for e in entries}
    if len(identities) != 1 or not all(next(iter(identities))):
        raise ValueError('selected delivered identity is missing or ambiguous')
    entry = entries[0]
    cert = entry['numeric_certificate']
    if cert.get('name') != champion or cert.get('shape_id') != entry['delivered_shape_id']:
        raise ValueError('selected registry certificate identity mismatch')
    book_dir = Path(entry['book_dir'])
    for path, expected in outputs.items():
        if path.is_relative_to(book_dir):
            if file_hash(_inside(path, book_dir)) != expected:
                raise ValueError('completed geometry source changed')
            evidence[str(path)] = expected
    original = entry.get('original_storey_evidence') or {}
    delivered = entry.get('delivered_floor_evidence') or {}
    if (not original.get('floor_elevations_m') or delivered.get('floors_removed_by_law')
            or original.get('floor_center_elevations_m') != delivered.get('delivered_floor_center_elevations_m')):
        raise ValueError('delivered facade floor-guide export is unavailable for altered floor elevations')
    return champion, entry, config, evidence


def reconstruct(name, entry, config):
    # The tracked BOOK owner retains the exact legal-fit and identity rules.
    owner = importlib.import_module('backend.app.modules.design.generation.maas.delivered_book_rebuild')
    from backend.app.modules.design.generation.maas.massv2.legal import load_legal_site
    from backend.app.modules.design.generation.maas.massv2.siting import site_open_side_direction
    from backend.app.modules.design.generation.maas.massv2.render_mesh import physical_triangles
    site = load_legal_site(config['pnu'], building_type=config['building_type'])
    source, _ = owner.rebuild_seat(name, {}, site, site.plan_at(0),
                                  site_open_side_direction(site) or (1, 0), 0, book_entry=entry)
    if source is None or owner.shape_id(source) != entry['delivered_shape_id']:
        raise ValueError('rebuilt delivered shape differs from judged shape')
    certificate = owner.seat_certificate(name, source, {}, site, book_entry=entry)
    if certificate['certificate_id'] != entry['numeric_certificate']['certificate_id']:
        raise ValueError('rebuilt certificate differs from judged certificate')
    # Exact indexing only: no welding tolerance, fitting, rounding or remeshing.
    vertices, faces, index = [], [], {}
    for triangle in physical_triangles(source):
        face = []
        for point in triangle:
            point = tuple(point)
            if point not in index:
                index[point] = len(vertices)
                vertices.append(list(point))
            face.append(index[point])
        faces.append(face)
    if not faces:
        raise ValueError('delivered mesh is empty')
    return {'vertices': vertices, 'triangles': faces}, certificate


def write_glb(mesh, path):
    """Serialize Z-up metre vertices as glTF Y-up; never reconstruct the form."""
    points = [[x, z, -y] for x, y, z in mesh['vertices']]
    positions = b''.join(struct.pack('<3f', *p) for p in points)
    indices = b''.join(struct.pack('<3I', *f) for f in mesh['triangles'])
    blob = positions + indices
    doc = {'asset': {'version': '2.0', 'generator': 'ARR delivered Mass'}, 'scene': 0,
           'scenes': [{'nodes': [0]}], 'nodes': [{'mesh': 0}],
           'meshes': [{'primitives': [{'attributes': {'POSITION': 0}, 'indices': 1}]}],
           'buffers': [{'byteLength': len(blob)}],
           'bufferViews': [{'buffer': 0, 'byteOffset': 0, 'byteLength': len(positions), 'target': 34962},
                           {'buffer': 0, 'byteOffset': len(positions), 'byteLength': len(indices), 'target': 34963}],
           'accessors': [{'bufferView': 0, 'componentType': 5126, 'count': len(points), 'type': 'VEC3',
                          'min': [min(p[i] for p in points) for i in range(3)],
                          'max': [max(p[i] for p in points) for i in range(3)]},
                         {'bufferView': 1, 'componentType': 5125, 'count': len(mesh['triangles']) * 3, 'type': 'SCALAR'}]}
    encoded = json.dumps(doc, separators=(',', ':')).encode()
    encoded += b' ' * (-len(encoded) % 4)
    blob += b'\0' * (-len(blob) % 4)
    path.write_bytes(struct.pack('<III', 0x46546C67, 2, 28 + len(encoded) + len(blob)) +
                     struct.pack('<II', len(encoded), 0x4E4F534A) + encoded +
                     struct.pack('<II', len(blob), 0x004E4942) + blob)


def build_package(candidate, staging, request):
    from backend.app.modules.design.generation.maas.creative_research_bundle import write_creative_mass_research_bundle
    bundle = write_creative_mass_research_bundle(candidate, run_directory=staging,
                run_id=request['source_run_id'], pnu=request['source_identity']['pnu'])
    package = staging / 'dataset/candidates' / candidate['candidate_id']
    package.mkdir(parents=True)
    shutil.copytree(staging / bundle['mass_directory'], package / 'mass')
    (package / 'candidate.json').write_text(json.dumps(candidate, ensure_ascii=False), encoding='utf-8')
    write_glb(candidate['mesh'], package / 'selected.glb')
    return package


def source_program(entry):
    if isinstance(entry.get('program'), dict):
        return entry['program']
    owner = importlib.import_module('backend.app.modules.design.generation.maas.delivered_book_records')
    records = owner.records_of(Path(entry['book_dir']))
    matching = [r for r in records if r.get('trace_sequence_name') == entry['trace']]
    if len(matching) != 1:
        raise ValueError('selected authored program is missing or ambiguous')
    program = (matching[0].get('geometry_artifact') or {}).get('authoredGeometryProgram')
    if not isinstance(program, dict):
        raise ValueError('selected authored program is unavailable')
    return program



def plan_handoff(mesh, entry, request):
    """Export certified sample sections, never assign statutory storey labels."""
    from math import isfinite
    from shapely.geometry import mapping
    from backend.app.modules.design.generation.maas.geometry_language.source_bridge import mesh_section_solid, solid_section_polygon
    evidence = entry.get('delivered_floor_evidence') or {}
    if (evidence.get('source_shape_id') != entry['delivered_shape_id']
            or evidence.get('measurement_consistent') is not True):
        raise ValueError('delivered floor measurement identity is not certified')
    centers = evidence.get('delivered_floor_center_elevations_m') or []
    areas = evidence.get('actual_floor_areas_m2') or []
    resolutions = evidence.get('export_area_comparison_resolution_m2') or []
    if not centers or not len(centers) == len(areas) == len(resolutions):
        raise ValueError('certified floor sample schedule is incomplete')
    if any(not isfinite(float(v)) for values in (centers, areas, resolutions) for v in values):
        raise ValueError('certified floor sample schedule is nonfinite')
    if any(a >= b for a, b in zip(centers, centers[1:])):
        raise ValueError('certified floor sample schedule is unordered')
    solid = mesh_section_solid(mesh['vertices'], mesh['triangles'])
    from backend.app.modules.design.generation.maas.occupied_floor_semantics import aligned_envelopes
    try:
        semantic_full, semantic_occupied, semantic_evidence = aligned_envelopes(source_program(entry), evidence)
        semantic_evidence['status'] = 'qualified'
    except (KeyError, ValueError, TypeError) as exc:
        semantic_full = semantic_occupied = None
        semantic_evidence = {'status': 'not_qualified', 'reason': str(exc),
            'scope': 'Complete solid sections are physical measurements, not qualified occupied capacity.'}
    floors = []
    for index, (z, area, resolution) in enumerate(zip(centers, areas, resolutions), 1):
        polygon = solid_section_polygon(solid, z)
        if (polygon is None or polygon.is_empty or not polygon.is_valid
                or polygon.geom_type not in ('Polygon', 'MultiPolygon')
                or area <= 0 or resolution < 0 or abs(polygon.area - area) > resolution):
            raise ValueError('delivered floor section area differs from certified measurement')
        row = {'floor': f'delivered-sample-{index:04d}', 'section_elevation_m': z,
            'polygon': json.loads(json.dumps(mapping(polygon))),
            'raw_solid_polygon': json.loads(json.dumps(mapping(polygon))),
            'raw_solid_area_m2': polygon.area, 'certified_raw_solid_area_m2': area,
            'capacity_status': 'not_qualified', 'capacity_basis': 'complete_solid_section'}
        if semantic_full is not None:
            reference = solid_section_polygon(semantic_full, z)
            occupied = solid_section_polygon(semantic_occupied, z)
            outside = polygon.difference(reference).area if reference is not None else polygon.area
            if outside > resolution:
                raise ValueError('semantic source construction differs from certified delivered section')
            qualified = polygon.intersection(occupied) if occupied is not None else polygon.intersection(polygon).difference(polygon)
            if qualified.is_empty or qualified.geom_type not in ('Polygon', 'MultiPolygon'):
                raise ValueError('source sample has no constructor-qualified occupied capacity')
            excluded = polygon.difference(qualified)
            row.update(polygon=json.loads(json.dumps(mapping(qualified))),
                capacity_status='qualified', capacity_basis='constructor_occupied_envelope',
                occupied_capacity_m2=qualified.area, excluded_support_area_m2=excluded.area,
                excluded_support_polygon=json.loads(json.dumps(mapping(excluded))),
                original_construction_reconciliation_m2=outside)
        floors.append(row)
    mass = {'floors': floors, 'source_mesh_hash': digest(mesh), 'floor_identity_basis': 'ordered certified delivered sample schedule',
            'semantic_evidence': semantic_evidence,
            'delivered_shape_id': entry['delivered_shape_id'],
            'certificate_id': entry['numeric_certificate']['certificate_id']}
    return {'schema_version': 'arr.delivered-mass-plan.v1',
            'status': 'ready' if semantic_full is not None else 'needs_evidence',
            'acceptance': 'not_evaluated', 'mass': mass, 'geometry_hash': digest(mass),
            'identity': {'name': entry['numeric_certificate']['name'],
                         'shape_id': entry['delivered_shape_id'],
                         'certificate_id': entry['numeric_certificate']['certificate_id']},
            **{key: request[key] for key in ('source_identity', 'source_versions', 'source_run_id')}}


def export_delivered_mass(request, *, roots=None, output_root=None):
    request_hash = digest(request)
    echo = {key: request.get(key) for key in ('source_run_id', 'source_identity', 'source_versions')}
    echo['request_hash'] = request_hash
    try:
        if 'include_plan' in request and type(request['include_plan']) is not bool:
            raise ValueError('include_plan must be boolean')
        if not isinstance(request.get('source_identity'), dict):
            raise ValueError('source_identity must be supplied')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', request.get('source_run_id', '')):
            raise ValueError('source_run_id must be an owner run identifier')
        if not isinstance(request.get('source_versions'), dict):
            raise ValueError('source_versions must be supplied')
        from backend.app.modules.massing.archive import preserved_export
        archived = preserved_export(request, request_hash)
        if archived is not None:
            return archived
        roots = roots if roots is not None else json.loads(os.environ.get(
            'EDITOR_MASS_WORKSPACE_ROOTS', json.dumps([os.environ.get('MASSV2_WS', str(DEFAULT_WORKSPACE))])))
        name, entry, config, evidence = selected_source(request, roots)
        output_root = Path(output_root or os.environ.get('EDITOR_DELIVERED_MASS_EXPORT_ROOT',
                           str(BACKEND / 'runtime/delivered-mass-exports'))).resolve()
        target = output_root / request_hash
        if target.exists():
            receipt = read(target / 'receipt.json')
            if receipt['request_hash'] != request_hash or receipt['evidence'] != evidence:
                raise ValueError('export receipt source evidence changed')
            actual = {p.relative_to(target).as_posix(): file_hash(p)
                      for p in target.rglob('*') if p.is_file() and p.name != 'receipt.json'}
            if actual != receipt['files']:
                raise ValueError('exported artifacts changed')
            return receipt['result']
        mesh, certificate = reconstruct(name, entry, config)
        plan = plan_handoff(mesh, entry, request) if request.get('include_plan') else None
        program = source_program(entry)
        candidate_id = 'mass-' + request_hash[:24]
        # These are authored guides, not a fresh statutory floor assessment.
        candidate = {'candidate_id': candidate_id, 'geometry_hash': digest(mesh),
            'program_hash': digest(program), 'geometry_program': program, 'mesh': mesh,
            'storey_evidence': entry.get('original_storey_evidence') or {},
            'source_identity': request['source_identity'], 'source_versions': request['source_versions'],
            'delivered_shape_id': entry['delivered_shape_id'], 'numeric_certificate': certificate,
            'authority': 'verified_delivered_source_mass', 'acceptance': 'not_evaluated'}
        output_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.export-', dir=output_root) as temporary:
            staging = Path(temporary)
            package = build_package(candidate, staging, request)
            if plan is not None:
                (staging / 'plan-handoff.json').write_text(json.dumps(plan, ensure_ascii=False, allow_nan=False), encoding='utf-8')
            if any(file_hash(path) != expected for path, expected in evidence.items()):
                raise ValueError('source evidence changed during export')
            files = {p.relative_to(staging).as_posix(): file_hash(p) for p in staging.rglob('*') if p.is_file()}
            final_package = target / package.relative_to(staging)
            glb = final_package / 'selected.glb'
            result = {**echo, 'status': 'succeeded',
                'identity': {'name': name, 'shape_id': entry['delivered_shape_id'],
                             'certificate_id': certificate['certificate_id']},
                'elevation_handoff': {'status': 'ready', 'acceptance': 'not_evaluated', 'request': {
                    'dataset_root': str(target / 'dataset'), 'candidate': candidate_id, 'run_id': candidate_id,
                    'selected_glb': str(glb), 'source_sha256': file_hash(package / 'selected.glb'),
                    'source_agent': 'mass', 'source_run_id': request['source_run_id'],
                    'source_versions': request['source_versions']}},
                **({'plan_handoff': {**plan, 'artifact': {'path': str(target / 'plan-handoff.json'),
                    'sha256': file_hash(staging / 'plan-handoff.json')}}} if plan is not None else {}),
                'artifacts': [{'kind': 'mass.delivered_package', 'path': str(target / path), 'sha256': value}
                              for path, value in sorted(files.items())]}
            (staging / 'receipt.json').write_text(json.dumps({'request_hash': request_hash, 'evidence': evidence,
                'files': files, 'result': result}, ensure_ascii=False), encoding='utf-8')
            staging.rename(target)
        return result
    except (OSError, ValueError, KeyError, TypeError, ImportError, RuntimeError) as exc:
        return {**echo, 'status': 'needs_evidence', 'code': 'delivered_mass_export_refused', 'reason': str(exc)}
