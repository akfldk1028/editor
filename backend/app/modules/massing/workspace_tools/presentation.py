"""Drawings whose filenames, sidecars and last frame identify the delivered mass."""

from backend.app.modules.massing import paths as _mass_paths
from backend.app.modules.design.generation import paths as _design_paths
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime

import hashlib
import json
from pathlib import Path


def artifact_stem(name, shape):
    return f'parti-{hashlib.sha256(name.encode()).hexdigest()[:12]}-{shape}'


def bound_sequence(folder, name, expected_shape):
    """A legacy sentence-only strip or altered PNG is not delivery evidence."""
    if not expected_shape:
        return None
    stem = artifact_stem(name, expected_shape)
    png = Path(folder) / (stem + '.png')
    manifest = png.with_suffix('.json')
    if not png.exists() or not manifest.exists():
        return None
    try:
        data = json.loads(manifest.read_text(encoding='utf-8'))
    except (ValueError, OSError):
        return None
    if (data.get('name') != name or data.get('shape_id') != expected_shape
            or data.get('final_shape_id') != expected_shape
            or data.get('png_sha256') != hashlib.sha256(png.read_bytes()).hexdigest()):
        return None
    return png


def sequence_frames(name, source, *, book, site, buildable, axis, certificate):
    """Authoring snapshots plus an explicit transition to the selected variant.

    BOOK intermediates are not reconstructed from verb names. Only their
    delivered geometry is shown when the import did not preserve snapshots.
    """
    from backend.app.modules.massing.workspace_tools.vlm_shortlist import shape_id
    if certificate['name'] != name or certificate['shape_id'] != shape_id(source):
        raise ValueError('sequence certificate does not identify its delivered source')
    frames = []
    record = book.get(name.split('~')[0].split('^')[0])
    if record and not name.startswith('book:'):
        from backend.app.modules.design.generation.maas.massv2.grammar import parti_from_record, declared_height_m
        from backend.app.modules.design.generation.maas.massv2.execute import execute_steps
        from backend.app.modules.design.generation.maas.massv2.compile import compile_matrix_form
        storey = certificate['storey_m']
        base = site.floor_height_m * max(1, int(site.far_capacity_m2 // max(1., site.ground_capacity_m2)))
        for op, form in execute_steps(parti_from_record(record), buildable=buildable,
                                      axis=axis, height_m=max(base, declared_height_m(record, storey)),
                                      storey_height_m=storey):
            intermediate = compile_matrix_form(form, storey_height_m=storey, allowed_at=site.plan_at)
            if intermediate is not None:
                frames.append({'source': intermediate, 'verb': op.verb,
                               'aim': '기본 조작 연구', 'why': op.why})
    frames.append({'source': source, 'verb': '선택 변형 · 최종 상태',
                   'aim': '배치와 법규 적용 후의 실제 전달 형상',
                   'why': ('앞 프레임은 기본 조작 연구이며, 이 프레임이 선택된 크기와 배치이다.'
                           if frames else 'BOOK 중간 형상 기록이 없어 최종 형상만 제시한다.'),
                   'numbers': f"건폐율 {certificate['coverage_pct']:.0f}%  용적률 {certificate['far_pct']:.0f}%"})
    return frames


def source_geometry_evidence(source):
    """Preserve existing compiler provenance; never invent a missing authority.

    BOOK's actual matrix trace lives in geometry_program_compilation.trace on
    the shared bridge. Keep that payload and the host-fit matrix evidence as
    written, without relabelling either as a MatrixForm. This JSON is delivery
    evidence; anonymous jurors still receive only their fixed prompt and PNGs.
    """
    fields = ('geometry_authority', 'matrix_form', 'geometry_program',
              'geometry_program_compilation', 'geometry_program_bridge_evidence',
              'matrix4_trace')
    metadata = source.metadata
    return {
        'schema_version': 'arr.maas.delivered_geometry_evidence.v1',
        'basis': 'existing final SourceMass compiler metadata; no reconstruction',
        'metadata': {key: metadata[key] for key in fields if metadata.get(key) is not None},
        'missing_metadata_fields': [key for key in fields if metadata.get(key) is None],
    }


def write_sequence(name, source, *, book, site, buildable, axis, out_dir,
                   certificate=None, anonymous=False):
    from backend.app.modules.massing.workspace_tools.vlm_shortlist import seat_certificate, shape_id
    from backend.app.modules.design.generation.maas.massv2.render import render_sequence
    cert = certificate or seat_certificate(name, source, book, site)
    frames = sequence_frames(name, source, book=book, site=site, buildable=buildable,
                             axis=axis, certificate=cert)
    target = Path(out_dir) / (artifact_stem(name, cert['shape_id']) + '.png')
    target.parent.mkdir(parents=True, exist_ok=True)
    # Always render fresh: matching geometry alone does not certify cached pixels.
    if anonymous:
        frames = [{**f, 'why': '', 'aim': ''} for f in frames]
    render_sequence(frames, target, site_ring=list(buildable.exterior.coords),
                    party_edges=site.shared_edges, heading='' if anonymous else name,
                    subheading='기본 조작 연구 / 선택 변형의 최종 상태' if not anonymous else '')
    manifest = {**cert, 'final_shape_id': shape_id(frames[-1]['source']),
                'frame_shape_ids': [shape_id(f['source']) for f in frames],
                'intermediate_basis': 'authored base studies' if len(frames) > 1 else 'unavailable',
                'png_sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
                'source_geometry_evidence': source_geometry_evidence(frames[-1]['source'])}
    target.with_suffix('.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return target


def _polygons(geometry):
    if geometry is None or geometry.is_empty:
        return []
    if geometry.geom_type == 'Polygon':
        return [geometry]
    return [p for g in getattr(geometry, 'geoms', ()) for p in _polygons(g)]


def _drawing_geometry(geometry):
    """The IR may return None for an unoccupied cut; draw/measure empty space.

    Preserve every supplied geometry unchanged. This presentation adapter
    neither substitutes the projected footprint nor changes the solid owner.
    """
    if geometry is None:
        from shapely.geometry import GeometryCollection
        return GeometryCollection()
    return geometry


def section_geometry(source, *, y):
    """Vertical x/z cut; top and underside come from the solid IR.

    The IR's surface mesh owns curved sampling; triangulation preserves holes.
    No rooms, entrances, floor slabs or circulation are invented.
    """
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    from backend.app.modules.design.generation.maas.massv2.render_mesh import is_mesh_authoritative, mesh_section_at
    if is_mesh_authoritative(source):
        return _drawing_geometry(mesh_section_at(source, axis='y', coordinate=y))
    height = float(source.metadata.get('authored_height_m') or 0)
    shapes = []
    for volume in source.volumes:
        low, high = volume.bottom_fraction * height, volume.top_fraction * height
        for triangle in volume.surface_mesh:
            intersections = []
            for a, b in zip(triangle, (*triangle[1:], triangle[0])):
                if abs(a[1] - y) < 1e-9:
                    intersections.append((a[0], low + a[2] * (high-low), low + a[3] * (high-low)))
                if (a[1] < y < b[1]) or (b[1] < y < a[1]):
                    t = (y-a[1]) / (b[1]-a[1])
                    values = tuple(a[i] + t*(b[i]-a[i]) for i in range(4))
                    intersections.append((values[0], low + values[2]*(high-low), low + values[3]*(high-low)))
            intersections = sorted(set(intersections))
            if len(intersections) < 2:
                continue
            a, b = intersections[0], intersections[-1]
            polygon = Polygon([(a[0], a[1]), (b[0], b[1]), (b[0], b[2]), (a[0], a[2])])
            if polygon.is_valid and polygon.area > 0:
                shapes.append(polygon)
    return unary_union(shapes)


def plan_geometry(source, *, z):
    """Occupied plan from the source's authority; BOOK requires its export mesh."""
    from backend.app.modules.design.generation.maas.massv2.render_mesh import is_mesh_authoritative, mesh_plan_at
    if is_mesh_authoritative(source):
        return _drawing_geometry(mesh_plan_at(source, z))
    if hasattr(source, 'plan_at'):
        return _drawing_geometry(source.plan_at(z))
    from shapely.ops import unary_union
    height = float(source.metadata.get('authored_height_m') or 0)
    return unary_union([v.plan_at(z, v.bottom_fraction * height, v.top_fraction * height)
                        for v in source.volumes])


def drawing_evidence(name, source, buildable, out_dir, *, storey_m=None, anonymous=False):
    """One common-scale ground/upper plan and a located vertical section."""
    from PIL import Image, ImageDraw, ImageFont
    from backend.app.modules.massing.workspace_tools.vlm_shortlist import shape_id
    from backend.app.modules.design.generation.maas.massv2.render_mesh import is_mesh_authoritative
    exact_mesh = is_mesh_authoritative(source)
    height = float(source.metadata.get('authored_height_m') or 0)
    datum = float(source.metadata.get('datum_m') or 0)
    cuts = [datum + 1.2, datum + (storey_m or height / 2) + 1.2]
    plans = [plan_geometry(source, z=z) for z in cuts]
    y = buildable.centroid.y
    section = section_geometry(source, y=y)
    canvas = Image.new('RGB', (1500, 590), 'white')
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default(size=18)
    xmin, ymin, xmax, ymax = buildable.bounds
    scale = min(440 / max(xmax - xmin, 1), 440 / max(ymax - ymin, height, 1))

    def paint(geometry, panel, section_view=False, fill='#d4d5cf'):
        def point(x, y):
            return (panel * 500 + 30 + (x - xmin) * scale,
                    510 - (y - (0 if section_view else ymin)) * scale)
        for poly in _polygons(geometry):
            draw.polygon([point(x, y) for x, y in poly.exterior.coords], fill=fill, outline='#323830')
            for ring in poly.interiors:
                draw.polygon([point(x, y) for x, y in ring.coords], fill='white', outline='#323830')

    for index, (plan, z) in enumerate(zip(plans, cuts)):
        paint(buildable, index, fill='white')
        paint(plan, index)
        yy = 510 - (y - ymin) * scale
        draw.line((index * 500 + 30, yy, index * 500 + 30 + (xmax - xmin) * scale, yy), fill='#ac6c45', width=2)
        draw.text((index * 500 + 25, 25), f'PLAN z={z - datum:.1f}m above ground / A-A cut', fill='black', font=font)
    paint(section, 2, True)
    draw.text((1025, 25), 'SECTION A-A / ' + ('export mesh section' if exact_mesh
              else 'solid outline, curves sampled'), fill='black', font=font)
    footer = 'common scale; no room layout or entrance assumed'
    if not anonymous:
        footer = f'{name} | {shape_id(source)} | ' + footer
    draw.text((25, 560), footer, fill='black', font=font)
    suffix = '-anonymous-drawings.png' if anonymous else '-drawings.png'
    target = Path(out_dir) / (artifact_stem(name, shape_id(source)) + suffix)
    canvas.save(target)
    target.with_suffix('.json').write_text(json.dumps({
        'name': name, 'shape_id': shape_id(source),
        'anonymous_image': anonymous,
        'image_footer': footer,
        'geometry_basis': 'complete_export_surface_mesh' if exact_mesh else 'source_volume_solid',
        'proxy_volumes_used': False,
        'plan_cuts_m': cuts, 'section_y_m': y,
        'plan_areas_m2': [plan.area for plan in plans], 'section_area_m2': section.area,
        'coordinate_basis': 'source world XY and mass-base Z; datum locates ground only',
        'png_sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
    }, ensure_ascii=False, indent=2), encoding='utf8')
    return target


def append_jury_drawings(tile_png, cases, buildable):
    """Append each compared source's anonymous plans/section under its axon.

    Cases are (private name, actual source, own storey height). Supporting
    sidecars stay outside the juror's image-only packet. No proxy reconstruction
    or caption/name substitution is allowed to stand in for these cuts.
    """
    from PIL import Image
    tile_png = Path(tile_png)
    evidence_dir = tile_png.parent / 'drawing-evidence'
    evidence_dir.mkdir(exist_ok=True)
    if not cases:
        raise ValueError('at least one delivered source is required')
    with Image.open(tile_png) as current:
        tile = current.convert('RGB')
    width = tile.width // len(cases)
    strips, evidence = [], []
    for name, source, storey in cases:
        path = drawing_evidence(name, source, buildable, evidence_dir,
                                storey_m=storey, anonymous=True)
        with Image.open(path) as drawing:
            height = max(1, round(drawing.height * width / drawing.width))
            strips.append(drawing.convert('RGB').resize((width, height), Image.Resampling.LANCZOS))
        evidence.append(json.loads(path.with_suffix('.json').read_text(encoding='utf8')))
    joined = Image.new('RGB', (tile.width, tile.height + max(p.height for p in strips)), 'white')
    joined.paste(tile, (0, 0))
    for i, strip in enumerate(strips):
        joined.paste(strip, (i * width, tile.height))
    joined.save(tile_png)
    return {'schema_version': 'arr.massv2.jury_drawings.v1', 'drawings': evidence}
