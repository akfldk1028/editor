"""Copy a receipted export and exact evidence bytes without rewriting any receipt."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile


def import_export(source, target):
    source, target = Path(source).resolve(), Path(target).resolve()
    receipt_bytes = (source / 'receipt.json').read_bytes()
    receipt = json.loads(receipt_bytes)
    key = receipt['request_hash']
    if len(key) != 64 or any(c not in '0123456789abcdef' for c in key):
        raise ValueError('Invalid export request hash')
    manifest_path = target / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {
        'schema': 'editor.mass-archive.v1', 'exports': {}, 'sources': {}}
    for original, expected in receipt['evidence'].items():
        previous = manifest['sources'].get(original)
        if previous is not None and previous['sha256'] != expected:
            raise ValueError(f'Preserved source identity has conflicting bytes: {original}')
    def copy(path, relative, expected):
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError(f'Original receipt no longer matches: {path}')
        dest = (target / relative).resolve()
        if not dest.is_relative_to(target):
            raise ValueError('Archive destination escapes owner')
        if dest.exists() and dest.read_bytes() != data:
            raise ValueError(f'Refusing to overwrite changed archive: {dest}')
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return {'path': dest.relative_to(target).as_posix(), 'sha256': expected}
    directory = Path('exports') / key
    for relative, expected in receipt['files'].items():
        file = (source / relative).resolve()
        if not file.is_relative_to(source):
            raise ValueError('Source export file escapes its package')
        copy(file, directory / relative, expected)
    for original, expected in receipt['evidence'].items():
        file = Path(original).resolve()
        manifest['sources'][original] = copy(file, Path('evidence') / expected / file.name, expected)
    manifest['exports'][key] = {
        'source_directory': str(source), 'directory': directory.as_posix(),
        'receipt': copy(source / 'receipt.json', directory / 'receipt.json', hashlib.sha256(receipt_bytes).hexdigest()),
    }
    descriptor, pending = tempfile.mkstemp(prefix='.manifest-', suffix='.json', dir=target)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, manifest_path)
    finally:
        Path(pending).unlink(missing_ok=True)
    return key


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('target', type=Path)
    args = parser.parse_args()
    print(import_export(args.source, args.target))
