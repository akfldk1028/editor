"""Elevation providers for worker-thread datum calculations, with actual provenance."""
import math
import os
from pathlib import Path
from urllib.parse import quote

import httpx

from backend.app.adapters.site_context import PROVIDER as SITE_PROVIDER, SiteHeightsError
from backend.app.adapters.site_context import ground_heights as site_ground_heights


class ElevationFetchError(RuntimeError):
    pass


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


class ElevationClient:
    def __init__(self, provider='open_meteo', *,
                 open_meteo_url='https://api.open-meteo.com/v1/elevation',
                 opentopodata_url=None, local_dem_path=None, transport=None, timeout=20):
        if not isinstance(provider, str) or not provider.strip():
            raise ValueError('Elevation provider is required')
        if not _number(timeout) or timeout <= 0:
            raise ValueError('Elevation timeout must be positive and finite')
        self.provider = provider
        self.open_meteo_url = open_meteo_url
        self.opentopodata_url = opentopodata_url
        self.local_dem_path = local_dem_path
        self.transport = transport
        self.timeout = timeout
        self._cache = {}
        self._providers = []

    @property
    def provenance(self):
        providers = list(self._providers)
        return {'configured_provider': self.provider, 'providers': providers,
                'actual_provider': providers[0] if len(providers) == 1 else ('mixed' if providers else None),
                'fallback_used': any(provider != self.provider for provider in providers)}

    def _identity(self):
        if self.provider == 'ngii_local_dem':
            path = self._local_path()
            try:
                stat = path.stat()
            except OSError:
                raise ElevationFetchError('Local elevation dataset unavailable') from None
            return self.provider, str(path.resolve()), stat.st_mtime_ns, stat.st_size
        if self.provider == SITE_PROVIDER:
            return (self.provider,)
        return self.provider, self.open_meteo_url, self.opentopodata_url

    def fetch(self, points):
        rounded = []
        for point in points:
            if (not isinstance(point, (tuple, list)) or len(point) != 2
                    or not all(_number(value) for value in point)
                    or not -90 <= point[0] <= 90 or not -180 <= point[1] <= 180):
                raise ElevationFetchError('Invalid elevation coordinates')
            # Fine local rasters must retain source sampling precision at pixel boundaries.
            rounded.append(tuple(point) if self.provider in ('ngii_local_dem', SITE_PROVIDER)
                           else (round(point[0], 5), round(point[1], 5)))
        if not rounded:
            return []
        identity = self._identity()
        missing = [point for point in dict.fromkeys(rounded) if (identity, point) not in self._cache]
        fresh = {}
        for offset in range(0, len(missing), 100):
            chunk = missing[offset:offset + 100]
            if self.provider == 'ngii_local_dem':
                values = self._local(chunk)
                sources = [self.provider] * len(chunk)
            elif self.provider == SITE_PROVIDER:
                # Site holds the NGII mosaic on its own server; strict like the local DEM.
                try:
                    values, _dataset = site_ground_heights(chunk, transport=self.transport)
                except SiteHeightsError:
                    raise ElevationFetchError('Site Context Agent ground heights unavailable') from None
                sources = [self.provider] * len(chunk)
            elif self.provider == 'open_meteo':
                values = self._open_meteo(chunk)
                sources = [self.provider] * len(chunk)
            else:
                try:
                    values = self._opentopodata(chunk)
                except ElevationFetchError:
                    values = [None] * len(chunk)
                sources = [self.provider] * len(chunk)
                fallback = [index for index, value in enumerate(values) if value is None]
                if fallback:
                    elevations = self._open_meteo([chunk[index] for index in fallback])
                    for index, elevation in zip(fallback, elevations):
                        values[index] = elevation
                        sources[index] = 'open_meteo'
            for point, value, source in zip(chunk, values, sources):
                fresh[(identity, point)] = (value, source)
        # Failed calls do not leave a partly populated cache or successful provenance.
        self._cache.update(fresh)
        results = [self._cache[(identity, point)] for point in rounded]
        self._providers = list(dict.fromkeys(self._providers + [source for _, source in results]))
        return [value for value, _ in results]

    def _get(self, url, params):
        if not url:
            raise ElevationFetchError('Elevation provider is not configured')
        try:
            with httpx.Client(transport=self.transport,
                              timeout=httpx.Timeout(self.timeout, connect=min(3, self.timeout)),
                              follow_redirects=False) as client:
                response = client.get(url, params=params)
                response.raise_for_status()
                value = response.json()
            if not isinstance(value, dict):
                raise ValueError('Invalid response')
            return value
        except (httpx.HTTPError, ValueError, TypeError):
            raise ElevationFetchError('Elevation provider request failed') from None

    def _open_meteo(self, points):
        payload = self._get(self.open_meteo_url,
            {'latitude': ','.join(f'{lat:.5f}' for lat, _ in points),
             'longitude': ','.join(f'{lng:.5f}' for _, lng in points)})
        values = payload.get('elevation')
        if (not isinstance(values, list) or len(values) != len(points)
                or not all(_number(value) for value in values)):
            raise ElevationFetchError('Elevation provider returned missing or invalid samples')
        return [float(value) for value in values]

    def _opentopodata(self, points):
        if not self.opentopodata_url:
            raise ElevationFetchError('Elevation dataset provider is not configured')
        payload = self._get(self.opentopodata_url.rstrip('/') + '/v1/' + quote(self.provider, safe=''),
            {'locations': '|'.join(f'{lat:.5f},{lng:.5f}' for lat, lng in points)})
        values = payload.get('results')
        if not isinstance(values, list) or len(values) != len(points):
            raise ElevationFetchError('Elevation dataset response shape is invalid')
        return [float(item['elevation']) if isinstance(item, dict) and _number(item.get('elevation'))
                else None for item in values]

    def _local_path(self):
        if not self.local_dem_path:
            raise ElevationFetchError('Local elevation dataset is not configured')
        value = str(self.local_dem_path)
        if os.name != 'nt' and len(value) >= 3 and value[1] == ':' and value[2] in ('/', '\\'):
            alternative = Path('/mnt') / value[0].lower() / value[3:].replace('\\', '/')
            if alternative.exists():
                return alternative
        return Path(value)

    def _local(self, points):
        try:
            import rasterio
            from pyproj import Transformer
            with rasterio.open(self._local_path()) as dataset:
                if dataset.crs is None or dataset.count < 1:
                    raise ValueError('Missing coordinate system or band')
                transform = Transformer.from_crs('EPSG:4326', dataset.crs, always_xy=True)
                coordinates = [transform.transform(lng, lat) for lat, lng in points]
                if not all(math.isfinite(x) and math.isfinite(y)
                           and dataset.bounds.left <= x < dataset.bounds.right
                           and dataset.bounds.bottom < y <= dataset.bounds.top for x, y in coordinates):
                    raise ValueError('Outside dataset bounds')
                values = []
                for sample in dataset.sample(coordinates, indexes=1, masked=True):
                    if len(sample) != 1 or bool(getattr(sample, 'mask', False)):
                        raise ValueError('Missing sample')
                    value = float(sample[0])
                    if (not math.isfinite(value) or not -500 <= value <= 9000
                            or (dataset.nodata is not None and value == dataset.nodata)):
                        raise ValueError('Invalid sample')
                    values.append(value)
                if len(values) != len(points):
                    raise ValueError('Missing samples')
                return values
        except Exception:
            # Local legal-datum requests must never silently switch to another DEM.
            raise ElevationFetchError('Local elevation dataset unavailable or missing samples') from None
