import hashlib
import os
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response


def create_scene_assets_router():
    router = APIRouter()

    @router.get('/scene-assets/{filename}')
    def scene_asset(filename: str):
        if not re.fullmatch(r'[a-f0-9]{64}\.glb', filename):
            raise HTTPException(404, 'Scene asset not found')
        storage = os.environ.get('EDITOR_PLATFORM_DATA_DIR')
        if not storage:
            raise HTTPException(503, 'Platform storage is not configured')
        root = (Path(storage) / 'scene-assets').resolve()
        path = root / filename
        if path.resolve().parent != root or not path.is_file():
            raise HTTPException(404, 'Scene asset not found')
        with path.open('rb') as source:
            content = source.read(64 * 1024 * 1024 + 1)
        if len(content) > 64 * 1024 * 1024:
            raise HTTPException(413, 'Scene asset is too large')
        if hashlib.sha256(content).hexdigest() != filename[:-4]:
            raise HTTPException(409, 'Scene asset checksum mismatch')
        return Response(content, media_type='model/gltf-binary', headers={
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
        })

    return router
