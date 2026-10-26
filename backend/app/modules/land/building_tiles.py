"""Serve prepared building data without starting a scene or agent process."""
import json
import os
import re
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse


def root():
    default = Path(__file__).resolve().parents[5] / 'agents/SceneAgent/runs/tiles'
    return Path(os.environ.get('WORLD_BUILDING_TILES_DIR') or default)


def archive(version):
    if not re.fullmatch(r'\d{8}-[0-9a-f]{8}', version):
        raise HTTPException(404, 'Unknown building tile version')
    path = root() / version / 'buildings.pmtiles'
    if not path.is_file():
        raise HTTPException(404, 'Building archive is not installed')
    return path


def latest(prefix):
    try:
        version = (root() / 'latest').read_text(encoding='utf-8').strip()
        path = archive(version)
        manifest = json.loads(path.with_name('manifest.json').read_text(encoding='utf-8'))
        if manifest.get('version') != version or manifest.get('layer') != 'buildings':
            raise ValueError('Invalid manifest')
    except (OSError, ValueError, HTTPException):
        raise HTTPException(503, 'Prepared building tiles are unavailable') from None
    href = f'{prefix}/building-tiles/{version}/buildings.pmtiles'
    return {k: manifest.get(k) for k in ('version', 'basis_date', 'built_at', 'bytes', 'zoom',
            'layer', 'properties', 'counts', 'licence')} | {'href': href, 'path': href}


def response(version):
    return FileResponse(archive(version), media_type='application/vnd.pmtiles',
                        headers={'Cache-Control': 'public, max-age=31536000, immutable'})
