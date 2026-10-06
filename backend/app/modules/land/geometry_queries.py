import hashlib
import json
import sqlite3

from shapely.errors import GEOSException
from starlette.concurrency import run_in_threadpool
from backend.app.adapters.vworld.geometry import GeometryProviderUnavailable
from .projection import geojson_to_polygon
from .zone_geometry import zone_areas
from .frontage import neighbor_roads, neighbor_parcels


class GeometryQueries:
    def __init__(self, provider, repository=None):
        self.provider = provider
        self.repository = repository

    async def split(self, geometry):
        errors = []
        try:
            parcel = geojson_to_polygon(geometry)
            key = hashlib.sha256(json.dumps(['LT_C_UQ111', list(parcel.bounds)]).encode()).hexdigest()
            try:
                features = await self.provider.zone_features(geometry)
            except GeometryProviderUnavailable as exc:
                cached = None
                if exc.cache_allowed and self.repository is not None:
                    try:
                        cached = await run_in_threadpool(self.repository.get_zone_cache, key)
                    except (OSError, ValueError, sqlite3.Error):
                        pass
                if cached is None:
                    raise
                features = cached['features']
                errors.append('Zone areas use cached provider features from ' + cached['fetched_at'])
            else:
                if features and self.repository is not None:
                    try:
                        await run_in_threadpool(self.repository.put_zone_cache, key, features)
                    except (OSError, ValueError, sqlite3.Error):
                        pass
            return await run_in_threadpool(zone_areas, parcel, features), errors
        except (GeometryProviderUnavailable, ValueError, TypeError, KeyError, AttributeError, GEOSException):
            return None, ['Zone area split unavailable']

    async def frontages(self, geometry):
        try:
            features = await self.provider.cadastral_features(geometry)
            roads = await run_in_threadpool(neighbor_roads, geometry, features)
            neighbors = await run_in_threadpool(neighbor_parcels, geometry, features)
            return roads.get('roads', []), neighbors.get('neighbors', []), []
        except (GeometryProviderUnavailable, ValueError, TypeError, KeyError, AttributeError, GEOSException):
            return [], [], ['Neighboring road and parcel lookup unavailable']
