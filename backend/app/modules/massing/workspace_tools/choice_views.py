"""Render additional views of the exact judged BOOK masses for client choice.

This reads an exported, evidence-bound source sheet. It never runs a production
stage, changes a score or writes inside completed round directories.
"""

from backend.app.modules.massing import paths as _mass_paths
from backend.app.modules.design.generation import paths as _design_paths
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime

import argparse
import hashlib
import json
import math
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--cameras', type=Path, help='Reviewed per-source low/reverse camera overrides')
    args = parser.parse_args()
    manifest_path = args.manifest.resolve()
    ws = _mass_paths.workspace_root()
    folder = manifest_path.parent
    if folder.parent != ws / 'runs' or not folder.name.startswith('presentation-'):
        raise ValueError('views require a separate presentation directory')
    manifest = read(manifest_path)
    cameras = read(args.cameras) if args.cameras else {}
    source_names = {r['source_name'] for r in manifest['representatives']}
    if not isinstance(cameras, dict) or set(cameras) - source_names:
        raise ValueError('camera overrides must name displayed sources')
    for source_views in cameras.values():
        if not isinstance(source_views, dict) or set(source_views) - {'low', 'reverse'}:
            raise ValueError('camera overrides must name low/reverse views')
        for camera in source_views.values():
            if not isinstance(camera, dict) or set(camera) != {'yaw_degrees', 'pitch_degrees'}:
                raise ValueError('camera requires yaw_degrees and pitch_degrees')
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                   for v in camera.values()):
                raise ValueError('camera angles must be finite numbers')
    for filename, digest in manifest['evidence'].items():
        if sha(filename) != digest:
            raise ValueError(f'changed source evidence: {filename}')
    if sha(folder / 'index.html') != manifest['html_sha256']:
        raise ValueError('sheet does not match manifest')

    from backend.app.modules.massing.workspace_tools.finalists import PNU, BUILDING_TYPE
    from backend.app.modules.massing.workspace_tools.book_import import entry_for_judged_row
    from backend.app.modules.massing.workspace_tools.vlm_shortlist import rebuild_seat, shape_id, seat_certificate
    from backend.app.modules.design.generation.maas.massv2.legal import load_legal_site
    from backend.app.modules.design.generation.maas.massv2.siting import site_open_side_direction
    from backend.app.modules.design.generation.maas.massv2.render import render_masses
    from backend.app.modules.design.generation.maas.massv2.render_mesh import physical_triangles

    site = load_legal_site(PNU, building_type=BUILDING_TYPE)
    buildable = site.plan_at(0)
    axis = site_open_side_direction(site) or (1, 0)
    out = folder / 'views'
    out.mkdir(exist_ok=True)
    rows = []
    for i, row in enumerate(manifest['representatives'], 1):
        entry = entry_for_judged_row(row)
        source, _ = rebuild_seat(row['name'], {}, site, buildable, axis, 0,
                                 book_entry=entry)
        if source is None or shape_id(source) != row['shape_id']:
            raise ValueError(f'rebuilt geometry differs from judged source: {row["name"]}')
        certificate = seat_certificate(row['name'], source, {}, site, book_entry=entry)
        if certificate['certificate_id'] != row['certificate_id']:
            raise ValueError(f'rebuilt certificate differs: {row["name"]}')
        triangles = physical_triangles(source)
        triangle_digest = hashlib.sha256(json.dumps(triangles, separators=(',', ':')).encode()).hexdigest()
        views = []
        for view_id, yaw, pitch in (('low', 145, 8), ('reverse', 25, 45)):
            camera = cameras.get(row['source_name'], {}).get(view_id, {})
            yaw = camera.get('yaw_degrees', yaw)
            pitch = camera.get('pitch_degrees', pitch)
            png = out / f'{i:02d}-{view_id}.png'
            render_masses([('', source, {})], png, site_ring=list(buildable.exterior.coords),
                          columns=1, tile=(880, 680), style='massing',
                          yaw_degrees=yaw, pitch_degrees=pitch)
            views.append(dict(id=view_id, path=str(png), sha256=sha(png),
                              yaw_degrees=yaw, pitch_degrees=pitch))
        if triangles != physical_triangles(source):
            raise ValueError('render changed source triangles')
        rows.append({k: row[k] for k in ('name', 'shape_id', 'certificate_id', 'source_program_hash')}
                    | dict(physical_triangles_sha256=triangle_digest, views=views))
        print(f'{i}/{len(manifest["representatives"])} exact additional views: {row["source_name"]}', flush=True)
    result = dict(schema='mass.book_choice_views.v1', round=manifest['round'],
                  geometry_basis='same rebuilt and certificate-matched judged SourceMass',
                  jury_images_changed=False, rows=rows)
    if args.cameras:
        result['reviewed_camera_input'] = dict(path=str(args.cameras.resolve()), sha256=sha(args.cameras))
    (folder / 'views.json').write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf8')


if __name__ == '__main__':
    main()
