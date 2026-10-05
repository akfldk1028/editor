"""Resolve immutable legacy export receipts to verified Editor-owned bytes."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from backend.app.modules.design.generation.paths import data_root


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def preserved_export(request, request_hash):
    root = data_root() / 'mass-archive'
    manifest_path = root / 'manifest.json'
    if not manifest_path.is_file():
        return None
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    entry = manifest.get('exports', {}).get(request_hash)
    if entry is None:
        return None
    root = root.resolve()
    def owned(relative, expected):
        path = (root / relative).resolve(strict=True)
        if not path.is_relative_to(root) or _sha(path) != expected:
            raise ValueError('Preserved mass archive bytes changed or escaped their owner')
        return path
    receipt_path = owned(entry['receipt']['path'], entry['receipt']['sha256'])
    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
    if receipt['request_hash'] != request_hash or receipt['result']['request_hash'] != request_hash:
        raise ValueError('Preserved export request identity changed')
    if receipt['evidence'].get(str(Path(request['completion_path']).resolve())) != request['completion_sha256']:
        raise ValueError('Preserved completion does not match requested bytes')
    for source, expected in receipt['evidence'].items():
        file = manifest['sources'][source]
        if file['sha256'] != expected:
            raise ValueError('Preserved source differs from original receipt')
        owned(file['path'], expected)
    target = (root / entry['directory']).resolve()
    if not target.is_relative_to(root):
        raise ValueError('Preserved export directory escapes owner')
    actual = {p.relative_to(target).as_posix(): _sha(p)
              for p in target.rglob('*') if p.is_file() and p.name != 'receipt.json'}
    if actual != receipt['files']:
        raise ValueError('Preserved export artifact set differs from receipt')
    old = Path(entry['source_directory'])
    def remap(value):
        if isinstance(value, dict):
            return {key: remap(item) for key, item in value.items()}
        if isinstance(value, list):
            return [remap(item) for item in value]
        if isinstance(value, str):
            path = Path(value)
            if path.is_absolute() and path.is_relative_to(old):
                return str(target / path.relative_to(old))
        return value
    # Only response locations change. Receipt, geometry, source identity and
    # artifact bytes remain exactly as originally accepted by their owners.
    return remap(deepcopy(receipt['result']))
