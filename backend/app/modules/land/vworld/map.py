import httpx


class MapUnavailable(Exception):
    pass


class VworldMapClient:
    def __init__(self, api_key, *, transport=None):
        self.api_key = api_key
        self.transport = transport

    async def _image(self, path, params=None):
        if not self.api_key:
            raise MapUnavailable('Map provider is not configured')
        try:
            async with httpx.AsyncClient(timeout=10, transport=self.transport) as client:
                async with client.stream('GET', 'https://api.vworld.kr/req/' + path, params=params) as response:
                    response.raise_for_status()
                    if response.headers.get('content-type', '').split(';')[0] != 'image/png':
                        raise ValueError('Invalid image')
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > 4 * 1024 * 1024:
                            raise ValueError('Image too large')
                    if not data.startswith(b'\x89PNG\r\n\x1a\n'):
                        raise ValueError('Invalid PNG')
                    return bytes(data)
        except (httpx.HTTPError, ValueError):
            # Provider URLs contain the key. Never propagate the upstream exception.
            raise MapUnavailable('Map provider image unavailable') from None

    async def tile(self, z, y, x):
        return await self._image(f'wmts/1.0.0/{self.api_key}/Base/{z}/{y}/{x}.png')

    async def wms(self, params):
        return await self._image('wms', {**params, 'key': self.api_key})
