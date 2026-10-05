"""Immutable owner drawings for gross-zone proposals, with explicit review limits."""
from hashlib import sha256
from html import escape
import json
from pathlib import Path

from shapely.geometry import shape


def _svg(floor, variant):
    features = variant['floor_plan']['features']
    footprint = shape(floor['body']['footprint_geojson'])
    minx, miny, maxx, maxy = footprint.bounds
    scale = min(700 / max(maxx - minx, 1), 620 / max(maxy - miny, 1))
    def point(x, y):
        return 40 + (x - minx) * scale, 110 + (maxy - y) * scale
    def ring(coords):
        return 'M ' + ' L '.join(f'{x:.5f},{y:.5f}' for x, y in (point(*c[:2]) for c in coords)) + ' Z'
    height = max(900, 220 + sum(not f['properties'].get('render_as_detail') for f in features) * 42)
    lines = [f'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="{height}" viewBox="0 0 1200 {height}">',
        f'<rect width="1200" height="{height}" fill="white"/>',
        f'<text x="40" y="35" font-family="sans-serif" font-size="22">Floor {floor["program_floor"]} / {escape(str(floor["mass_floor"]))} / ALT {variant["design_id"] + 1}</text>',
        '<text x="40" y="65" font-family="sans-serif" font-size="15" fill="#b45309">GROSS FUNCTIONAL ZONES - NOT NET ROOMS - DESIGN REVIEW REQUIRED</text>']
    if variant.get('proposal_kind') == 'core_circulation':
        lines[-1] = '<text x="40" y="65" font-family="sans-serif" font-size="15" fill="#b45309">UNSELECTED CORE / CIRCULATION PROPOSAL - CONDITIONAL BASIS - NOT LEGAL APPROVAL</text>'
        source_parts = list(footprint.geoms) if footprint.geom_type == 'MultiPolygon' else [footprint]
        source_path = ' '.join(ring(part.exterior.coords) + ' ' + ' '.join(ring(hole.coords) for hole in part.interiors)
                               for part in source_parts)
        lines.append(f'<path data-role="source-footprint" d="{source_path}" fill="#f8fafc" fill-rule="evenodd" stroke="#0f172a" stroke-width="2"/>')
    if variant.get('candidate_status') == 'rejected':
        lines.append('<text x="40" y="90" font-family="sans-serif" font-size="17" fill="#b91c1c">REJECTED: fragmented reservation geometry - diagnostic preview only</text>')
    legend_index = 0
    for feature in features:
        properties = feature['properties']
        geometry = shape(feature['geometry'])
        parts = list(geometry.geoms) if geometry.geom_type == 'MultiPolygon' else [geometry]
        path = ' '.join(ring(part.exterior.coords) + ' ' + ' '.join(ring(hole.coords) for hole in part.interiors) for part in parts)
        lines.append(f'<path d="{path}" fill="{properties["color"]}" fill-rule="evenodd" stroke="#334155" stroke-width="1"/>')
        if properties.get('render_as_detail'):
            continue
        index = legend_index
        legend_index += 1
        label = geometry.representative_point()
        x, y = point(label.x, label.y)
        lines.append(f'<text x="{x:.3f}" y="{y:.3f}" text-anchor="middle" font-family="sans-serif" font-size="13">{index + 1}</text>')
        name = escape(properties['room_name'])
        sid = escape(properties['space_id'])
        lines.append(f'<text x="780" y="{115 + index * 42}" font-family="sans-serif" font-size="13">{index + 1}. {name}</text>')
        lines.append(f'<text x="780" y="{132 + index * 42}" font-family="sans-serif" font-size="11" fill="#475569">{sid}: {properties["area_m2"]:.3f} m² gross</text>')
    lines.append(f'<text x="40" y="{height - 60}" font-family="sans-serif" font-size="14" fill="#b45309">Pending: net rooms, circulation, cores, egress, accessibility, Law and parking review.</text>')
    lines.append('</svg>')
    return '\n'.join(lines).encode('utf-8')


def publish(directory, floor, variant):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    refs = []
    documents = [('svg', 'image/svg+xml', _svg(floor, variant)),
        ('geojson', 'application/geo+json', json.dumps(variant['floor_plan'], sort_keys=True,
            separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8'))]
    for extension, media_type, content in documents:
        digest = sha256(content).hexdigest()
        path = directory / f'floor-{floor["program_floor"]}-alt-{variant["design_id"]}-{digest[:16]}.{extension}'
        if path.exists():
            if path.read_bytes() != content:
                raise ValueError('Immutable Plan artifact changed')
        else:
            with path.open('xb') as handle:
                handle.write(content)
        refs.append({'path': str(path), 'sha256': digest, 'media_type': media_type,
            'role': ('rejected_plan_' if variant.get('candidate_status') == 'rejected' else 'plan_') + extension, 'program_floor': floor['program_floor'],
            'mass_floor': floor['mass_floor'], 'design_id': variant['design_id']})
    return refs
