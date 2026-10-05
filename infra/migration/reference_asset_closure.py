"""Copy only passport-referenced corpus files, preserving existing data and bytes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import unquote, urlsplit


def _sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def referenced_urls(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, str) and (key in {'url', 'href'} or key.endswith('_url')):
                yield item
            else:
                yield from referenced_urls(item)
    elif isinstance(value, list):
        for item in value:
            yield from referenced_urls(item)


def copy_referenced_assets(urls, source_root, destination_root, *, dry_run=False):
    source_root, destination_root = Path(source_root).resolve(), Path(destination_root).resolve()
    relative_paths = set()
    for url in urls:
        parsed = urlsplit(url)
        if parsed.scheme or parsed.netloc:
            continue
        for prefix in ('/design/maas/reference-assets/', '/api/v1/design/maas/reference-assets/'):
            if parsed.path.startswith(prefix):
                relative_paths.add(unquote(parsed.path[len(prefix):]))
    rows = []
    for relative in sorted(relative_paths):
        source, destination = (source_root / relative).resolve(), (destination_root / relative).resolve()
        if not source.is_relative_to(source_root) or not destination.is_relative_to(destination_root):
            raise ValueError('Asset path escapes its corpus root')
        if not source.is_file():
            raise FileNotFoundError(source)
        digest = _sha(source)
        if destination.exists() and (not destination.is_file() or _sha(destination) != digest):
            raise ValueError(f'Existing asset conflict: {relative}')
        rows.append({'relative': relative, 'source': str(source), 'destination': str(destination),
                     'sha256': digest, 'bytes': source.stat().st_size, 'existed': destination.exists()})
    total_bytes = sum(row['bytes'] for row in rows)
    if total_bytes > 256 * 1024 * 1024:
        raise ValueError('Referenced closure exceeds the 256 MiB bounded migration limit')
    copied = 0
    if not dry_run:
        for row in rows:
            if row['existed']:
                continue
            destination = Path(row['destination'])
            destination.parent.mkdir(parents=True, exist_ok=True)
            payload = Path(row['source']).read_bytes()
            if hashlib.sha256(payload).hexdigest() != row['sha256']:
                raise ValueError('Source changed after inventory')
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(payload)
                # Linking a verified temporary file creates the final name atomically
                # and fails if another process has created it after the inventory.
                os.link(temporary, destination)
                copied += 1
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
    return {'schema': 'editor.reference-asset-closure.v1', 'dry_run': dry_run,
            'files': rows, 'total_bytes': total_bytes, 'copied': copied}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--editor-data', required=True, type=Path)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    from backend.app.modules.design.workspace_archive import WorkspaceArchive
    archive = WorkspaceArchive(args.editor_data.resolve())
    runs, _ = archive.index()
    urls = set()
    for run_id, items in runs.items():
        for index in items:
            urls.update(referenced_urls(archive.passport(run_id, index)))
    target = args.editor_data / 'docs/ai-session-memory/reference-corpus'
    print(json.dumps(copy_referenced_assets(urls, args.source_root, target, dry_run=args.dry_run), indent=2))


if __name__ == '__main__':
    main()
