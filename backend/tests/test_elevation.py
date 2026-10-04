import json

import httpx
import pytest

from backend.app.adapters.elevation import ElevationClient, ElevationFetchError


def test_batches_deduplicates_and_caches_with_provenance():
    sizes = []
    def respond(request):
        count = len(request.url.params['latitude'].split(','))
        sizes.append(count)
        return httpx.Response(200, json={'elevation': [12.5] * count})
    client = ElevationClient(transport=httpx.MockTransport(respond))
    points = [(37 + i / 1000, 127) for i in range(205)]
    assert client.fetch(points + points[:2]) == [12.5] * 207
    assert sizes == [100, 100, 5]
    assert client.fetch(points) == [12.5] * 205
    assert sizes == [100, 100, 5]
    assert client.provenance['actual_provider'] == 'open_meteo'


@pytest.mark.parametrize('value', [None, True, '12', float('nan'), float('inf')])
def test_open_meteo_invalid_values_never_become_zero(value):
    def respond(request):
        return httpx.Response(200, content=json.dumps({'elevation': [value]}))
    client = ElevationClient(transport=httpx.MockTransport(respond))
    with pytest.raises(ElevationFetchError): client.fetch([(37, 127)])
    assert client.provenance['actual_provider'] is None


def test_partial_fallback_provenance_survives_cache():
    calls = []
    def respond(request):
        calls.append(request.url.host)
        if request.url.host == 'dataset':
            return httpx.Response(200, json={'results': [{'elevation': 10}, {'elevation': None}]})
        return httpx.Response(200, json={'elevation': [20]})
    client = ElevationClient('ngii_lidar_1m', opentopodata_url='http://dataset',
                            transport=httpx.MockTransport(respond))
    points = [(37, 127), (37.1, 127)]
    assert client.fetch(points) == [10, 20]
    assert client.provenance['actual_provider'] == 'mixed'
    assert client.provenance['fallback_used'] is True
    assert client.fetch(points) == [10, 20]
    assert client.provenance['actual_provider'] == 'mixed'
    assert len(calls) == 2


def test_total_fallback_failure_is_safe_error_and_never_cached():
    calls = []
    def respond(request):
        calls.append(True)
        raise httpx.ConnectError('secret provider URL')
    client = ElevationClient('dataset', opentopodata_url='http://secret',
                            transport=httpx.MockTransport(respond))
    for _ in range(2):
        with pytest.raises(ElevationFetchError) as exc: client.fetch([(37, 127)])
        assert 'secret' not in str(exc.value)
    assert len(calls) == 4


def test_provider_url_is_part_of_cache_identity():
    def respond(request):
        return httpx.Response(200, json={'elevation': [1 if request.url.host == 'one' else 2]})
    client = ElevationClient(open_meteo_url='http://one', transport=httpx.MockTransport(respond))
    assert client.fetch([(37, 127)]) == [1]
    client.open_meteo_url = 'http://two'
    assert client.fetch([(37, 127)]) == [2]


def test_local_missing_file_is_strict_and_safe(tmp_path):
    client = ElevationClient('ngii_local_dem', local_dem_path=tmp_path / 'secret.tif')
    with pytest.raises(ElevationFetchError) as exc: client.fetch([(37, 127)])
    assert 'secret' not in str(exc.value)


def test_local_dem_coverage_nodata_and_crs(tmp_path):
    rasterio = pytest.importorskip('rasterio')
    import numpy as np
    from rasterio.transform import from_origin
    path = tmp_path / 'local.tif'
    with rasterio.open(path, 'w', driver='GTiff', height=2, width=2, count=1,
                       dtype='float32', crs='EPSG:4326', transform=from_origin(127, 38, .1, .1),
                       nodata=-9999) as dataset:
        dataset.write(np.array([[12, -9999], [14, 15]], dtype='float32'), 1)
    client = ElevationClient('ngii_local_dem', local_dem_path=path)
    assert client.fetch([(37.95, 127.05)]) == [12]
    assert client.provenance['actual_provider'] == 'ngii_local_dem'
    for point in [(37.95, 127.15), (37, 128)]:
        with pytest.raises(ElevationFetchError): client.fetch([point])
    import os
    previous = path.stat().st_mtime_ns
    with rasterio.open(path, 'r+') as dataset:
        dataset.write(np.array([[22, -9999], [14, 15]], dtype='float32'), 1)
    os.utime(path, ns=(previous + 1_000_000_000, previous + 1_000_000_000))
    assert client.fetch([(37.95, 127.05)]) == [22]


def test_local_dem_preserves_submeter_coordinate_precision(tmp_path):
    rasterio = pytest.importorskip('rasterio')
    import numpy as np
    from rasterio.transform import from_origin
    path = tmp_path / 'precise.tif'
    with rasterio.open(path, 'w', driver='GTiff', height=1, width=2, count=1,
                       dtype='float32', crs='EPSG:4326',
                       transform=from_origin(127, 37.00001, .000004, .00001)) as dataset:
        dataset.write(np.array([[11, 22]], dtype='float32'), 1)
    client = ElevationClient('ngii_local_dem', local_dem_path=path)
    assert client.fetch([(37.000006, 127.0000039), (37.000006, 127.0000041)]) == [11, 22]


def test_provenance_accumulates_across_fetches_in_one_calculation():
    def respond(request):
        if request.url.host == 'dataset':
            missing = request.url.params['locations'].startswith('37.00000')
            return httpx.Response(200, json={'results': [{'elevation': None if missing else 5}]})
        return httpx.Response(200, json={'elevation': [20]})
    client = ElevationClient('dataset', opentopodata_url='http://dataset',
                            transport=httpx.MockTransport(respond))
    client.fetch([(37, 127)])
    client.fetch([(38, 127)])
    assert client.provenance['actual_provider'] == 'mixed'


@pytest.mark.parametrize('mode', ['valid', 'nodata', 'outside', 'no_crs'])
def test_local_dem_strict_without_optional_dependency(tmp_path, monkeypatch, mode):
    import sys
    from types import SimpleNamespace
    path = tmp_path / 'local.tif'
    path.write_bytes(b'fixture')
    class Sample(list):
        mask = False
    class Dataset:
        crs = None if mode == 'no_crs' else 'EPSG:4326'
        count = 1
        nodata = -9999
        bounds = SimpleNamespace(left=126, right=128, bottom=36, top=38)
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def sample(self, coordinates, **kwargs):
            return [Sample([-9999 if mode == 'nodata' else 12]) for _ in coordinates]
    monkeypatch.setitem(sys.modules, 'rasterio', SimpleNamespace(open=lambda path: Dataset()))
    client = ElevationClient('ngii_local_dem', local_dem_path=path)
    point = (39, 127) if mode == 'outside' else (37, 127)
    if mode == 'valid': assert client.fetch([point]) == [12]
    else:
        with pytest.raises(ElevationFetchError): client.fetch([point])
