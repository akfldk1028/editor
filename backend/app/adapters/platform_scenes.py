from urllib.parse import quote
import httpx

from backend.app.adapters.orchestrator import OwnerContractError, OwnerUnavailable


class SceneNotFound(Exception):
    pass


class PlatformScenes:
    def __init__(self, base_url: str | None, *, transport=None):
        self.base_url, self.transport = base_url, transport

    async def get_scene(self, scene_id):
        if not self.base_url:
            raise OwnerUnavailable()
        try:
            async with httpx.AsyncClient(timeout=8, transport=self.transport, follow_redirects=False) as client:
                response = await client.get(self.base_url.rstrip('/') + '/api/scenes/' + quote(scene_id, safe=''))
                if response.status_code == 404:
                    raise SceneNotFound()
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise OwnerUnavailable() from exc
        try:
            data = response.json()
            if (not isinstance(data, dict) or type(data.get('version')) is not int or data['version'] < 0
                or not isinstance(data.get('id'), str) or not data['id']
                or 'projectId' not in data or data['projectId'] is not None and not isinstance(data['projectId'], str)):
                raise ValueError('invalid scene response')
            if 'ownerId' not in data or data['ownerId'] is not None and not isinstance(data['ownerId'], str):
                raise ValueError('invalid scene ownership')
            return {key: data.get(key) for key in ('id', 'projectId', 'version', 'ownerId')}
        except ValueError as exc:
            raise OwnerContractError() from exc
