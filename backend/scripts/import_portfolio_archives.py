"""Copy validated historical catalog closures without rewriting their evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

from PIL import Image
from backend.app.modules.design.generation.maas.creative_portfolio_catalog import creative_portfolio_manifest
from backend.app.modules.design.generation.maas.portfolio_evaluation_catalog import portfolio_evaluation_manifest

KINDS = {'creative': 'maas-creative-portfolio.json', 'evaluations': 'maas-portfolio-evaluation.json'}


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inside(root, path):
    resolved = path.resolve()
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError(f'Archive reference is missing or outside source root: {path}')
    return resolved


def validate(root, kind, run):
    reader = creative_portfolio_manifest if kind == 'creative' else portfolio_evaluation_manifest
    return reader(root, run)


def plan_archive(source, kind, runs=None):
    root = Path(source).resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    filename = KINDS[kind]
    selected = sorted(set(runs)) if runs else sorted(p.parent.name for p in root.glob(f'*/{filename}'))
    if not selected:
        raise FileNotFoundError(f'No {kind} runs in {root}')
    files = set()
    candidates = 0
    for run in selected:
        manifest = validate(root, kind, run)
        directory = root / run
        files.add(inside(root, directory / filename))
        candidates += manifest['candidate_count']
        if kind == 'creative':
            files.add(inside(root, directory / manifest['board_png']))
            for row in manifest['candidates']:
                for field in ('candidate_json', 'render_png', 'mass_manifest', 'elevation_research_handoff'):
                    files.add(inside(root, directory / row[field]))
                # MASS folders carry the archived evidence referenced by each member.
                mass = (directory / row['mass_directory']).resolve()
                for path in mass.rglob('*'):
                    if path.is_file():
                        files.add(inside(root, path))
        else:
            for row in manifest['candidates']:
                if row['preview_path']:
                    raw = Path(row['preview_path'])
                    if raw.is_absolute():
                        raise ValueError('Absolute preview paths require explicit archival remapping; source bytes will not be changed')
                    files.add(inside(root, directory / raw))
    rows = []
    for path in sorted(files):
        if path.suffix.lower() == '.png':
            try:
                with Image.open(path) as image:
                    if image.format != 'PNG':
                        raise ValueError('Not PNG')
                    image.verify()
            except Exception as exc:
                raise ValueError(f'Invalid PNG: {path}') from exc
        rows.append({'path': path.relative_to(root).as_posix(), 'size': path.stat().st_size,
                     'mtime_ns': path.stat().st_mtime_ns, 'sha256': digest(path)})
    return {'schema_version': 'editor.portfolio_archive_import.v1',
            'archive_status': 'preserved_source_archive', 'source_root': str(root),
            'kind': kind, 'runs': selected, 'candidate_count': candidates,
            'file_count': len(rows), 'total_bytes': sum(row['size'] for row in rows), 'files': rows}


def migrate_archive(source, destination, kind, runs=None):
    plan = plan_archive(source, kind, runs)
    return copy_archive_plan(source, destination, plan, lambda target: [validate(target, kind, run) for run in plan['runs']])


def copy_archive_plan(source, destination, plan, verify_destination):
    root, target = Path(source).resolve(), Path(destination).resolve()
    if target == root or target.is_relative_to(root) or root.is_relative_to(target):
        raise ValueError('Source and destination must be separate archive trees')
    manifest = target / 'archive-import-manifest.json'
    encoded = (json.dumps(plan, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    if manifest.exists() and manifest.read_bytes() != encoded:
        raise FileExistsError(f'Different import manifest already exists: {manifest}')
    # Preflight every collision before creating any destination files.
    for row in plan['files']:
        out = target / row['path']
        if not out.resolve().is_relative_to(target):
            raise ValueError(f'Destination escapes archive root: {out}')
        if out.exists() and (not out.is_file() or digest(out) != row['sha256']):
            raise FileExistsError(out)
    for row in plan['files']:
        src, out = root / row['path'], target / row['path']
        out.parent.mkdir(parents=True, exist_ok=True)
        if not out.exists():
            with src.open('rb') as reader, out.open('xb') as writer:
                shutil.copyfileobj(reader, writer)
            shutil.copystat(src, out)
        if digest(out) != row['sha256']:
            raise ValueError(f'Copied archive hash mismatch: {out}')
    # Replaying the target proves that runtime reads need no original server/files.
    verify_destination(target)
    if not manifest.exists():
        with manifest.open('xb') as stream:
            stream.write(encoded)
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--destination', required=True)
    parser.add_argument('--kind', choices=KINDS, required=True)
    parser.add_argument('--run', action='append')
    parser.add_argument('--apply', action='store_true', help='Copy the inspected closure; default only validates and reports size')
    args = parser.parse_args()
    result = (migrate_archive(args.source, args.destination, args.kind, args.run) if args.apply
              else plan_archive(args.source, args.kind, args.run))
    print(json.dumps({key: value for key, value in result.items() if key != 'files'}, indent=2))


if __name__ == '__main__':
    main()
