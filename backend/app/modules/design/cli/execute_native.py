"""Compute one saved additive specification without claiming worker ownership.

Usage: python -m backend.app.modules.design.cli.execute_native --help
The final manifest is the commit marker; incomplete attempt directories are
preserved and require a different attempt ID for an explicit restart.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from backend.app.modules.design.artifacts import _linked
from backend.app.modules.design.native_repository import NativeJobRepository, canonical_json


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _safe_path(path):
    if any(_linked(item) for item in (path, *path.parents)):
        raise ValueError('Linked computation output paths are not supported')


def _atomic_write(path, data):
    _safe_path(path)
    if path.exists():
        raise FileExistsError(f'Output already exists: {path.name}')
    descriptor, temporary = tempfile.mkstemp(prefix=f'.{path.name}.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        _safe_path(path)
        if path.exists():
            raise FileExistsError(f'Output already exists: {path.name}')
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _validate_result(value, seed):
    if (not isinstance(value, dict) or value.get('status') not in ('computed', 'cancelled')
            or value.get('algorithm') != 'additive' or value.get('engine_version') != 'additive-ssiea-v1'
            or type(value.get('seed')) is not int or value['seed'] != seed
            or value.get('legal_compliance_verified') is not False
            or value.get('evidence_mode') != 'unverified_search'
            or type(value.get('total_evaluated')) is not int or value['total_evaluated'] < 0
            or any(not isinstance(value.get(key), list) for key in ('candidates', 'rejections', 'events'))
            or not isinstance(value.get('effective_spec'), dict)):
        raise ValueError('Invalid additive computation result')
    effective = canonical_json(value['effective_spec']).encode('utf-8')
    if value.get('effective_spec_sha256') != _sha(effective):
        raise ValueError('Effective execution specification checksum mismatch')


def execute_saved_job(repository, actor, project_id, job_id, *, seed, output_root,
                      attempt_id, unverified_search, compute_fn=None):
    if unverified_search is not True:
        raise ValueError('Explicit unverified search mode is required')
    if type(seed) is not int or not 0 <= seed < 2**64:
        raise ValueError('Seed must be an unsigned 64-bit integer')
    if not isinstance(attempt_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', attempt_id):
        raise ValueError('Invalid computation attempt ID')
    root = Path(output_root)
    if not root.is_absolute():
        raise ValueError('Computation output root must be absolute')
    _safe_path(root)
    job = repository.get_job(actor, project_id, job_id)
    if job is None:
        raise LookupError('Native job not found in the requested actor/project scope')
    if job['algorithm'] != 'additive' or job['prepared']['algorithm'] != 'additive':
        raise ValueError('This consumer supports additive computation only')
    prepared_bytes = canonical_json(job['prepared'], max_bytes=4*1024*1024, max_depth=36).encode('utf-8')
    prepared = json.loads(prepared_bytes)
    if compute_fn is None:
        from backend.app.modules.design.optimization.service import compute
        compute_fn = compute
    root.mkdir(parents=True, exist_ok=True)
    _safe_path(root)
    attempt = root / attempt_id
    _safe_path(attempt)
    attempt.mkdir()
    value = compute_fn(prepared, seed=seed, limits=None, envelope=None)
    _validate_result(value, seed)
    result_bytes = canonical_json(value, max_bytes=32*1024*1024, max_depth=48, max_nodes=2000000).encode('utf-8')
    manifest = {
        'contract_version': 'editor-native-computation/v1',
        'attempt_id': attempt_id, 'actor': actor, 'project_id': project_id, 'job_id': job_id,
        'scene_id': job['scene_id'], 'scene_revision': job['scene_revision'],
        'input_sha256': job['input_sha256'], 'prepared_sha256': _sha(prepared_bytes),
        'seed': seed, 'algorithm': 'additive', 'engine_version': value['engine_version'],
        'effective_spec_sha256': value['effective_spec_sha256'],
        'status': value['status'], 'evidence_mode': 'unverified_search',
        'legal_compliance_verified': False, 'lifecycle_managed': False,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'total_evaluated': value['total_evaluated'],
        'candidate_count': len(value['candidates']), 'rejection_count': len(value['rejections']),
        'result': {'path': 'result.json', 'size': len(result_bytes), 'sha256': _sha(result_bytes)},
    }
    manifest_bytes = canonical_json(manifest).encode('utf-8')
    _atomic_write(attempt / 'result.json', result_bytes)
    _atomic_write(attempt / 'manifest.json', manifest_bytes)
    return manifest


def _seed(text):
    if not re.fullmatch(r'[0-9]{1,20}', text) or int(text) >= 2**64:
        raise argparse.ArgumentTypeError('Seed must be an unsigned 64-bit integer')
    return int(text)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Compute a saved additive specification; no legal verification or durable worker lifecycle.')
    parser.add_argument('--storage-directory', required=True)
    parser.add_argument('--actor', required=True)
    parser.add_argument('--project-id', required=True)
    parser.add_argument('--job-id', required=True)
    parser.add_argument('--seed', required=True, type=_seed)
    parser.add_argument('--output-root', required=True)
    parser.add_argument('--attempt-id', required=True)
    parser.add_argument('--unverified-search', required=True, action='store_true')
    args = parser.parse_args(argv)
    try:
        value = execute_saved_job(NativeJobRepository(args.storage_directory), args.actor, args.project_id,
            args.job_id, seed=args.seed, output_root=args.output_root, attempt_id=args.attempt_id,
            unverified_search=args.unverified_search)
    except (ValueError, LookupError, OSError, RuntimeError) as error:
        parser.exit(1, f'Computation was not published: {error}\n')
    print(canonical_json(value))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
