"""The Mass form the person chose, standing on the chosen layout, read into the site map's `mass` shape.

After the 매스 설계 pick (`mass_selection`) the Orchestrator has Mass deliver the chosen form and the editor's export
door (`design/generation/maas/delivered/mass_export.py`) writes it under `export_root()`: a receipt naming the
source run, and the candidate's mesh in site-local metres (EPSG:32652 minus `origin_utm`) with its storey
elevations. The Orchestrator's `mass_export` communication row carries no text, so the chosen mass is read here
from that export, the editor's own record. The 3D view draws a mass as volumes (a WGS84 ring from `base_m` to
`top_m`, `world/lib/layout-masses.ts`), so each storey band is cut from the mesh at its middle height.
"""
from __future__ import annotations

import json
from pathlib import Path

from backend.app.modules.platform.run_results.common import _dict, _num, _str

TOOL = 'mass_export'
MIN_PLAN_M2 = 1.0


def _receipt_for(run_id, root):
    """The newest export receipt of `run_id` under `root`: (export dir, result) or None."""
    found = []
    for receipt in Path(root).glob('*/receipt.json'):
        try:
            result = _dict(json.loads(receipt.read_text(encoding='utf-8')).get('result'))
        except (OSError, ValueError):
            continue
        if _str(result.get('source_run_id')) == run_id and result.get('status') == 'succeeded':
            found.append((receipt.stat().st_mtime, receipt.parent, result))
    if not found:
        return None
    _, folder, result = max(found, key=lambda item: item[0])
    return folder, result


def plan_rings(mesh, z):
    """The plans (site-local metres: `ring` and its `holes`) of the solid `mesh` cut by the plane at height `z`."""
    from shapely.geometry import LineString, Polygon
    from shapely.ops import polygonize, unary_union
    vertices, segments = mesh['vertices'], []
    for triangle in mesh['triangles']:
        points = []
        for a, b in ((0, 1), (1, 2), (2, 0)):
            (x1, y1, z1), (x2, y2, z2) = vertices[triangle[a]], vertices[triangle[b]]
            if (z1 < z) != (z2 < z):
                t = (z - z1) / (z2 - z1)
                # Snapped: the same edge met from its two triangles must give one point, or the ring never closes.
                points.append((round(x1 + t * (x2 - x1), 6), round(y1 + t * (y2 - y1), 6)))
        if len(points) == 2 and points[0] != points[1]:
            segments.append(LineString(points))
    if not segments:
        return []
    faces = [face.simplify(0.01) for face in polygonize(unary_union(segments)) if face.area >= MIN_PLAN_M2]
    # A courtyard cuts as two faces, the ring and the court inside it; the court is the ring's hole, not a plan.
    plans = []
    for face in faces:
        if any(other is not face and Polygon(other.exterior).contains(face.representative_point()) for other in faces):
            continue
        plans.append({'ring': [[round(x, 3), round(y, 3)] for x, y in face.exterior.coords],
                      'holes': [[[round(x, 3), round(y, 3)] for x, y in hole.coords] for hole in face.interiors]})
    return plans


def volumes_of(candidate):
    """One volume per storey band and plan ring, in WGS84 (pyproj from the candidate's frame)."""
    from pyproj import Transformer
    frame = _dict(candidate.get('coordinate_frame'))
    origin = frame.get('origin_utm')
    mesh = _dict(candidate.get('mesh'))
    if (not isinstance(origin, list) or len(origin) != 2 or not _str(frame.get('crs'))
            or not isinstance(mesh.get('vertices'), list) or not isinstance(mesh.get('triangles'), list)):
        return []
    floors = [_num(v) for v in _dict(candidate.get('storey_evidence')).get('floor_elevations_m') or []]
    floors = [v for v in floors if v is not None]
    top = _num(_dict(candidate.get('numeric_certificate')).get('height_m'))
    if top is None:
        top = max((v[2] for v in mesh['vertices'] if isinstance(v, list) and len(v) == 3), default=None)
    if top is None:
        return []
    if len(floors) < 2:
        floors = [0.0, top]
    if floors[-1] < top:
        floors.append(top)
    to_wgs84 = Transformer.from_crs(frame['crs'], 'EPSG:4326', always_xy=True)

    def wgs84(ring):
        return [[round(lng, 7), round(lat, 7)] for lng, lat in
                (to_wgs84.transform(x + origin[0], y + origin[1]) for x, y in ring)]
    volumes = []
    for base, upper in zip(floors, floors[1:]):
        if upper - base <= 0.05:
            continue
        for plan in plan_rings(mesh, (base + upper) / 2):
            volumes.append({'ring': wgs84(plan['ring']), 'holes': [wgs84(hole) for hole in plan['holes']],
                            'base_m': round(base, 2), 'top_m': round(upper, 2)})
    return volumes


def glb_href(result, request):
    """The selected glTF's API-relative link. mass_export adds `selected_glb_href` only to the reply it returns
    (`with_links`); receipt.json keeps absolute paths, so the link is formed here the same way."""
    href = _str(request.get('selected_glb_href'))
    if href:
        return href
    glb, root, request_hash = _str(request.get('selected_glb')), _str(request.get('dataset_root')), _str(result.get('request_hash'))
    if not (glb and root and request_hash):
        return None
    try:
        relative = Path(glb).relative_to(Path(root).parent).as_posix()
    except ValueError:
        return None
    return f'design/maas/delivered-mass-export/{request_hash}/files/{relative}'


def model_of(candidate, href):
    """The delivered mesh itself for the 3D view: its glTF (site-local metres, y up, origin at `origin_utm`), the
    WGS84 point of that origin, and the bearing of the frame's grid north (UTM grid north is not true north; on
    684-1, zone 52 at 127.1 E, about 1.2 degrees). Storey volumes cut at mid-height lose sloped roofs and notches;
    the person's chosen form is drawn as delivered."""
    import math
    from pyproj import Transformer
    frame = _dict(candidate.get('coordinate_frame'))
    origin = frame.get('origin_utm')
    if not href or not isinstance(origin, list) or len(origin) != 2 or not _str(frame.get('crs')):
        return None
    try:   # a frame this host cannot read leaves the model out, never the whole run's results
        to_wgs84 = Transformer.from_crs(frame['crs'], 'EPSG:4326', always_xy=True)
        lng, lat = to_wgs84.transform(origin[0], origin[1])
        lng_n, lat_n = to_wgs84.transform(origin[0], origin[1] + 100.0)
    except Exception:  # noqa: BLE001 - pyproj raises CRSError / ProjError / TypeError
        return None
    if not all(math.isfinite(v) for v in (lng, lat, lng_n, lat_n)):
        return None
    east = math.radians(lng_n - lng) * math.cos(math.radians(lat))
    north = math.radians(lat_n - lat)
    return {'href': href, 'origin': [round(lng, 8), round(lat, 8)],
            'heading_deg': round(math.degrees(math.atan2(east, north)), 4)}


def parse(run, rows, root=None):
    """None until the run's export succeeded; then the chosen form as the 3D view stands it on the layout."""
    if not any(row.get('tool') == TOOL and _str(row.get('state')) == 'succeeded' for row in rows):
        return None
    run_id = _str(_dict(run).get('run_id'))
    if not run_id:
        return None
    if root is None:
        from backend.app.modules.design.generation.maas.delivered.mass_export import export_root
        root = export_root()
    found = _receipt_for(run_id, root)
    if found is None:
        return None
    folder, result = found
    request = _dict(_dict(result.get('elevation_handoff')).get('request'))
    candidate_id = _str(request.get('candidate'))
    try:
        candidate = json.loads((folder / 'dataset' / 'candidates' / candidate_id / 'candidate.json').read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError):
        return None
    certificate = _dict(candidate.get('numeric_certificate'))
    identity = _dict(result.get('identity'))
    return {'status': 'chosen', 'selected_mass_id': _str(result.get('selected_mass_id')),
            'selection_mode': _str(result.get('selection_mode')),
            'label': _str(identity.get('shape_id')) or _str(identity.get('name')),
            'storeys': _num(_dict(candidate.get('storey_evidence')).get('storey_count')),
            'height_m': _num(certificate.get('height_m')), 'ground_m2': _num(certificate.get('ground_m2')),
            'gross_m2': _num(certificate.get('gross_m2')), 'volumes': volumes_of(candidate),
            'glb_href': glb_href(result, request),
            'model': model_of(candidate, glb_href(result, request))}
