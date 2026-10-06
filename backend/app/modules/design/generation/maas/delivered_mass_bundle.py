"""Export a Mass cycle that arrives as content from another server.

Agents share no disk: the Mass host zips the completed cycle (request.json,
workspace/<relative path>, sources/<i>/<relative path>) and the editor exports it
exactly as a local cycle, with the Mass-host paths pinned in state.json remapped
onto a private staging copy. The request identity excludes those paths.
"""
import io
import json
from pathlib import Path
import re
import shutil
import uuid
import zipfile

from backend.app.modules.design.generation.maas.delivered_mass_export import export_delivered_mass, export_root

MAX_MEMBERS = 20000
MAX_MEMBER_BYTES = 1024 * 1024 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
REQUEST_KEYS = {'completion_sha256', 'source_run_id', 'source_identity', 'source_versions'}
OPTIONAL_KEYS = {'include_plan'}
_SOURCE = re.compile(r'sources/[0-9]+')
_ABSOLUTE = re.compile(r'/|[A-Za-z]:[\\/]|\\\\')
_UNSAFE_PART = re.compile(r'[\x00-\x1f:*?"<>|]|[. ]$|^(?i:(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?)$')


class BundleRefused(ValueError):
    """The bundle itself is malformed or unsafe (HTTP 400), not a refused export."""


def member_parts(name):
    """Return the path parts of a safe relative member name, else refuse."""
    if not name or name.startswith('/') or '\\' in name or re.match(r'[A-Za-z]:', name):
        raise BundleRefused(f'unsafe bundle member: {name!r}')
    parts = name.split('/')
    if any(part in ('', '.', '..') or _UNSAFE_PART.search(part) for part in parts):
        raise BundleRefused(f'unsafe bundle member: {name!r}')
    if not (parts == ['request.json'] or (parts[0] == 'workspace' and len(parts) > 1)
            or (parts[0] == 'sources' and len(parts) > 2 and parts[1].isdigit())):
        raise BundleRefused(f'unexpected bundle member: {name!r}')
    return parts


def extract(body, staging):
    try:
        archive = zipfile.ZipFile(io.BytesIO(body))
    except zipfile.BadZipFile:
        raise BundleRefused('bundle must be a zip archive') from None
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_MEMBERS:
            raise BundleRefused('bundle has too many members')
        total = 0
        for info in infos:
            # orig_filename is the raw name; zipfile rewrites backslashes in .filename on Windows.
            if info.is_dir():
                member_parts(info.orig_filename.rstrip('/'))
                continue
            destination = staging.joinpath(*member_parts(info.orig_filename))
            if info.file_size > MAX_MEMBER_BYTES:
                raise BundleRefused('bundle member is too large')
            destination.parent.mkdir(parents=True, exist_ok=True)
            size = 0
            # 'xb' refuses duplicate (or case-colliding) names instead of overwriting.
            with archive.open(info) as source, open(destination, 'xb') as target:
                while chunk := source.read(1024 * 1024):
                    size += len(chunk)
                    total += len(chunk)
                    if size > MAX_MEMBER_BYTES or total > MAX_TOTAL_BYTES:
                        raise BundleRefused('bundle is too large')
                    target.write(chunk)


def staged_request(staging):
    """Read request.json; return the canonical request, the staged completion and the origin map."""
    try:
        manifest = json.loads((staging / 'request.json').read_text(encoding='utf-8'),
                              parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        request, cycle, origins = manifest['request'], manifest['round'], manifest['origins']
        workspace, sources = origins['workspace'], origins['sources']
    except (OSError, ValueError, KeyError, TypeError):
        raise BundleRefused('request.json must carry request, round and origins') from None
    if (not isinstance(request, dict) or not REQUEST_KEYS <= set(request)
            or set(request) - REQUEST_KEYS - OPTIONAL_KEYS):
        raise BundleRefused('request must be the canonical export request (no completion_path)')
    if not isinstance(cycle, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', cycle):
        raise BundleRefused('round must be a cycle round identifier')
    if (not isinstance(workspace, str) or not _ABSOLUTE.match(workspace) or not isinstance(sources, dict)
            or any(not isinstance(origin, str) or not _ABSOLUTE.match(origin)
                   or not isinstance(local, str) or not _SOURCE.fullmatch(local)
                   for origin, local in sources.items())):
        raise BundleRefused('origins must map absolute Mass-host paths to workspace and sources/<i>')
    mapping = {workspace: staging / 'workspace',
               **{origin: staging.joinpath(*local.split('/')) for origin, local in sources.items()}}
    completion = staging / 'workspace' / 'runs' / f'cycle-{cycle}' / 'complete.json'
    return request, completion, mapping


def export_bundle(body, *, output_root=None):
    """Stage, export with remapped paths, and always remove the staging folder."""
    root = export_root(output_root)
    staging = root / '.incoming' / uuid.uuid4().hex
    staging.mkdir(parents=True)
    try:
        extract(body, staging)
        request, completion, origins = staged_request(staging)
        (staging / 'workspace').mkdir(exist_ok=True)
        return export_delivered_mass(request, roots=[staging / 'workspace'], output_root=root,
                                     origins=origins, source_roots=[staging], completion_path=str(completion))
    finally:
        shutil.rmtree(staging, ignore_errors=True)
