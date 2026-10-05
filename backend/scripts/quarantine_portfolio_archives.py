"""Preserve failed creative archives separately from the active runtime catalog."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

from PIL import Image
from backend.scripts.import_portfolio_archives import copy_archive_plan, digest, inside, validate


def validation_failure(root, run):
    try:
        validate(root, 'creative', run)
    except (ValueError, TypeError, KeyError, OSError) as exc:
        return {'run': run, 'error_type': type(exc).__name__, 'reason': str(exc),
                'source_manifest_sha256': digest(root / run / 'maas-creative-portfolio.json')}
    raise ValueError(f'Run passes active catalog validation and is not eligible for failure quarantine: {run}')


def plan_quarantine(source, runs):
    root = Path(source).resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    selected = sorted(set(runs))
    if not selected:
        raise ValueError('Explicit failed run selection is required')
    files, failures, image_failures = set(), [], []
    candidates = 0
    for run in selected:
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', run):
            raise ValueError('Invalid quarantine run ID')
        directory = (root / run).resolve()
        if not directory.is_relative_to(root):
            raise ValueError('Quarantine run escapes source root')
        manifest_path = inside(directory, directory / 'maas-creative-portfolio.json')
        failures.append(validation_failure(root, run))
        payload = json.loads(manifest_path.read_text(encoding='utf-8'))
        files.update([manifest_path, inside(directory, directory / 'maas-creative-board.png')])
        candidates += len(payload['candidates'])
        for summary in payload['candidates']:
            candidate_path = inside(directory, directory / summary['candidate_json'])
            files.add(candidate_path)
            candidate = json.loads(candidate_path.read_text(encoding='utf-8'))
            # Retain both sets of original references when a mismatch itself is evidence.
            for row in (summary, candidate):
                for field in ('candidate_json', 'render_png', 'mass_manifest', 'elevation_research_handoff'):
                    if row.get(field):
                        files.add(inside(directory, directory / row[field]))
                if row.get('mass_directory'):
                    mass = (directory / row['mass_directory']).resolve()
                    if not mass.is_relative_to(directory) or not mass.is_dir():
                        raise ValueError(f'Invalid quarantine MASS directory: {mass}')
                    files.update(inside(directory, path) for path in mass.rglob('*') if path.is_file())
    rows = []
    for path in sorted(files):
        relative = path.relative_to(root).as_posix()
        if path.suffix.lower() == '.png':
            try:
                with Image.open(path) as image:
                    if image.format != 'PNG':
                        raise ValueError('Not PNG')
                    image.verify()
            except Exception as exc:
                image_failures.append({'path': relative, 'error_type': type(exc).__name__, 'reason': str(exc)})
        rows.append({'path': relative, 'size': path.stat().st_size,
                     'mtime_ns': path.stat().st_mtime_ns, 'sha256': digest(path)})
    return {'schema_version': 'editor.portfolio_archive_quarantine.v1',
            'archive_status': 'quarantined_validation_failure', 'active_catalog_eligible': False,
            'source_root': str(root), 'kind': 'creative', 'runs': selected,
            'candidate_count': candidates, 'validation_failures': failures, 'image_failures': image_failures,
            'file_count': len(rows), 'total_bytes': sum(row['size'] for row in rows), 'files': rows}


def quarantine_archives(source, destination, runs):
    target = Path(destination).resolve()
    if target.name != 'creative-portfolios' or target.parent.name != 'archive-quarantine':
        raise ValueError('Quarantine destination must be archive-quarantine/creative-portfolios; never an active catalog')
    plan = plan_quarantine(source, runs)
    def verify_destination(root):
        for expected in plan['validation_failures']:
            actual = validation_failure(root, expected['run'])
            # Absolute paths in OSError text change after relocation; bytes and failure type do not.
            if actual['error_type'] != expected['error_type'] or actual['source_manifest_sha256'] != expected['source_manifest_sha256']:
                raise ValueError(f"Quarantined failure provenance changed: {expected['run']}")
            if actual['error_type'] == 'ValueError' and actual['reason'] != expected['reason']:
                raise ValueError(f"Quarantined validation reason changed: {expected['run']}")
    return copy_archive_plan(source, target, plan, verify_destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit', required=True, help='Source audit JSON containing source_root and excluded_runs')
    parser.add_argument('--destination', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    audit = json.loads(Path(args.audit).read_text(encoding='utf-8'))
    runs = [row['run'] for row in audit['excluded_runs']]
    result = (quarantine_archives(audit['source_root'], args.destination, runs) if args.apply
              else plan_quarantine(audit['source_root'], runs))
    print(json.dumps({key: value for key, value in result.items() if key != 'files'}, indent=2))


if __name__ == '__main__':
    main()
