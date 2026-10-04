"""Byte-preserving archive of execution artifacts, independent of legacy paths."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile


class ArtifactArchiveError(ValueError):
    pass


def _identity(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}', value):
        raise ArtifactArchiveError('Invalid source identity')
    return value


def _relative(value):
    if (not isinstance(value, str) or not value or '\\' in value or ':' in value
            or PurePosixPath(value).is_absolute() or any(p in ('', '.', '..') for p in value.split('/'))):
        raise ArtifactArchiveError('Invalid relative artifact path')
    return value


def _linked(path):
    return path.is_symlink() or path.is_junction()


def _safe_path(root, relative):
    path = root
    for part in PurePosixPath(_relative(relative)).parts:
        path = path / part
        if _linked(path):
            raise ArtifactArchiveError('Linked archive paths are not supported')
    return path


def _digest(path):
    digest = hashlib.sha256()
    before = path.stat()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ArtifactArchiveError('Artifact changed during capture')
    return {'sha256': digest.hexdigest(), 'size': after.st_size}


def _scan(root):
    result = {}
    def reject_unreadable(error):
        raise error
    for directory, dirs, files in os.walk(root, followlinks=False, onerror=reject_unreadable):
        for name in dirs + files:
            path = Path(directory) / name
            if _linked(path):
                raise ArtifactArchiveError('Linked source paths are not supported')
        for name in sorted(files):
            path = Path(directory) / name
            if not path.is_file():
                raise ArtifactArchiveError('Non-file source entry')
            relative = _relative(path.relative_to(root).as_posix())
            result[relative] = _digest(path)
    if not result:
        raise ArtifactArchiveError('Empty source archive')
    return dict(sorted(result.items()))


class ArtifactArchive:
    def __init__(self, directory):
        path = Path(directory)
        if not path.is_absolute():
            raise ArtifactArchiveError('Archive directory must be absolute')
        if any(_linked(p) for p in (path, *path.parents)):
            raise ArtifactArchiveError('Linked archive root is not supported')
        self.directory = path.resolve()

    def _manifest(self, source_id):
        return _safe_path(self.directory, f'manifests/{_identity(source_id)}.json')

    def entries(self, source_id):
        path = self._manifest(source_id)
        if not path.exists():
            return {}
        try:
            document = json.loads(path.read_text(encoding='utf-8'))
            if document['schema'] != 'editor-design-artifacts/v1' or document['source_id'] != source_id:
                raise ArtifactArchiveError('Invalid archive manifest')
            entries = document['entries']
            if not isinstance(entries, dict) or not entries:
                raise ArtifactArchiveError('Invalid archive entries')
            for name, entry in entries.items():
                _relative(name)
                if (not isinstance(entry, dict) or not re.fullmatch('[a-f0-9]{64}', entry.get('sha256', ''))
                        or type(entry.get('size')) is not int or entry['size'] < 0):
                    raise ArtifactArchiveError('Invalid archive entry')
            return entries
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise ArtifactArchiveError('Invalid archive manifest') from error

    def _blob(self, entry):
        return _safe_path(self.directory, 'blobs/' + entry['sha256'])

    def file(self, source_id, relative):
        entry = self.entries(source_id).get(_relative(relative))
        if entry is None:
            raise ArtifactArchiveError('Unknown artifact')
        path = self._blob(entry)
        if not path.is_file() or _digest(path) != entry:
            raise ArtifactArchiveError('Missing or corrupt artifact')
        return path


def import_artifacts(archive, source, source_id, *, dry_run=True):
    _identity(source_id)
    source = Path(source)
    if not source.is_absolute() or not source.is_dir() or any(_linked(p) for p in (source, *source.parents)):
        raise ArtifactArchiveError('Source must be an unlinked absolute directory')
    source = source.resolve()
    if source == archive.directory or source in archive.directory.parents or archive.directory in source.parents:
        raise ArtifactArchiveError('Source and destination must be disjoint')
    entries = _scan(source)
    previous = archive.entries(source_id)
    if any(entries.get(name) != entry for name, entry in previous.items()):
        raise ArtifactArchiveError('Existing artifact changed or disappeared; use a new snapshot identity')
    for entry in previous.values():
        blob = archive._blob(entry)
        if not blob.is_file() or _digest(blob) != entry:
            raise ArtifactArchiveError('Existing archive is corrupt')
    report = {'source_id': source_id, 'dry_run': dry_run, 'files': len(entries),
              'bytes': sum(e['size'] for e in entries.values()), 'added': len(entries) - len(previous),
              'snapshot_sha256': hashlib.sha256(json.dumps(entries, sort_keys=True, separators=(',', ':')).encode()).hexdigest()}
    if dry_run:
        return report
    archive.directory.mkdir(parents=True, exist_ok=True)
    lock = _safe_path(archive.directory, 'import.lock')
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise ArtifactArchiveError('Archive import already locked') from error
    os.close(descriptor)
    try:
        if archive.entries(source_id) != previous:
            raise ArtifactArchiveError('Archive changed during capture; retry')
        for name, entry in entries.items():
            blob = archive._blob(entry)
            blob.parent.mkdir(parents=True, exist_ok=True)
            if blob.exists():
                if _digest(blob) != entry:
                    raise ArtifactArchiveError('Content-addressed blob is corrupt')
                continue
            fd, temporary = tempfile.mkstemp(dir=blob.parent, prefix='capture-')
            try:
                with os.fdopen(fd, 'wb') as output, _safe_path(source, name).open('rb') as original:
                    for chunk in iter(lambda: original.read(1024 * 1024), b''):
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                if _digest(Path(temporary)) != entry:
                    raise ArtifactArchiveError('Source changed during copy')
                os.replace(temporary, blob)
            finally:
                Path(temporary).unlink(missing_ok=True)
        # A second content scan detects changes across the capture interval.
        if _scan(source) != entries:
            raise ArtifactArchiveError('Source changed during capture; manifest not published')
        manifest = archive._manifest(source_id)
        manifest.parent.mkdir(parents=True, exist_ok=True)
        document = {'schema': 'editor-design-artifacts/v1', 'source_id': source_id,
                    'execution_state': 'archived', 'entries': entries}
        fd, temporary = tempfile.mkstemp(dir=manifest.parent, prefix='manifest-')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as output:
                json.dump(document, output, ensure_ascii=False, sort_keys=True, indent=2)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, manifest)
        finally:
            Path(temporary).unlink(missing_ok=True)
    finally:
        lock.unlink()
    return report
