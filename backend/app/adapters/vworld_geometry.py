"""Async feature retrieval only; geometry calculations and caches live outside."""
import httpx
from shapely.geometry import shape

from backend.app.modules.land.parcel_geometry import parcel_geometry
from backend.app.modules.land.projection import geojson_to_polygon


class GeometryProviderUnavailable(RuntimeError):
    def __init__(self, message: str, *, cache_allowed: bool = False):
        super().__init__(message)
        self.cache_allowed = cache_allowed


class VworldGeometryClient:
    def __init__(self, api_key: str, *, transport=None):
        self.api_key = api_key
        self.transport = transport

    async def zone_features(self, parcel_geojson: dict) -> list[dict]:
        return await self._features(parcel_geojson, layer='LT_C_UQ111', pad=0.0008, size=300,
                                    referer=True)

    async def cadastral_features(self, parcel_geojson: dict) -> list[dict]:
        return await self._features(parcel_geojson, layer='LP_PA_CBND_BUBUN', pad=0.0002, size=100)

    async def _features(self, parcel_geojson, *, layer, pad, size, referer=False):
        if not self.api_key:
            raise GeometryProviderUnavailable('Vworld geometry lookup is not configured')
        geometry = parcel_geometry(parcel_geojson)
        # The original two providers select different MultiPolygon parts.
        if referer:
            query_geometry = geojson_to_polygon(geometry)
        else:
            query_geometry = shape(geometry)
            if geometry['type'] == 'MultiPolygon':
                query_geometry = query_geometry.geoms[0]
        min_x, min_y, max_x, max_y = query_geometry.bounds
        params = {'key': self.api_key, 'service': 'data', 'request': 'GetFeature', 'data': layer,
                  'geomFilter': f'BOX({min_x-pad},{min_y-pad},{max_x+pad},{max_y+pad})',
                  'format': 'json', 'crs': 'EPSG:4326', 'size': str(size)}
        headers = {}
        if referer:
            params['domain'] = 'http://localhost'
            headers['Referer'] = 'http://localhost'
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=httpx.Timeout(20, connect=5),
                                         follow_redirects=False) as client:
                response = await client.get('https://api.vworld.kr/req/data', params=params, headers=headers)
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError):
            # Only transport/JSON failures were eligible for the source cache.
            raise GeometryProviderUnavailable('Vworld geometry request failed', cache_allowed=True) from None
        if not isinstance(payload, dict) or not isinstance(payload.get('response'), dict):
            raise GeometryProviderUnavailable('Invalid Vworld geometry response')
        body = payload['response']
        if body.get('status') != 'OK':
            raise GeometryProviderUnavailable('Vworld geometry provider did not return OK')
        result = body.get('result')
        collection = result.get('featureCollection') if isinstance(result, dict) else None
        features = collection.get('features') if isinstance(collection, dict) else None
        if (not isinstance(features, list)
                or not all(isinstance(feature, dict) and
                           (feature.get('properties') is None or isinstance(feature.get('properties'), dict))
                           for feature in features)):
            raise GeometryProviderUnavailable('Invalid Vworld geometry feature collection')
        return features
