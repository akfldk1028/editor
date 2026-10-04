from dataclasses import asdict
import importlib
import json
from pathlib import Path

import pytest
from shapely.geometry import shape


FIXTURE = json.loads((Path(__file__).parent / 'fixtures/land_datum_source.json').read_text(encoding='utf-8'))


class Provider:
    provenance = {'actual_provider': 'fixture'}

    def __init__(self, slope=0, bad=None):
        self.slope, self.bad = slope, bad

    def fetch(self, points):
        if self.bad is not None:
            return self.bad
        return [10+(lat-37)*self.slope for lat, lng in points]


@pytest.mark.parametrize('case', FIXTURE['cases'], ids=lambda case: case['name'])
def test_datum_source_differential(case):
    module = importlib.import_module('backend.app.modules.land.datum')
    context = module.DatumContext(shape(case['parcel']),
        shape(case['road']) if case['road'] else None, shape(case['neighbor']) if case['neighbor'] else None,
        case['apply_neighbor'], case['apply_road'])
    result = module.DatumService(Provider(case['slope'])).compute(context)
    serialized = asdict(result)
    assert serialized.pop('provenance') == {'actual_provider':'fixture'}
    assert serialized == case['expected']


@pytest.mark.parametrize('bad', [[], [float('nan')], [float('inf')], [True], ['10']])
def test_invalid_provider_response_never_becomes_absolute_zero(bad):
    module = importlib.import_module('backend.app.modules.land.datum')
    context = module.DatumContext(shape(FIXTURE['cases'][0]['parcel']))
    result = module.DatumService(Provider(bad=bad)).compute(context)
    assert result.elevation_source == 'failed'
    assert result.elevation_m is None


def test_settings_reject_zero_sampling_step():
    module = importlib.import_module('backend.app.modules.land.datum')
    with pytest.raises(ValueError):
        module.DatumSettings(edge_subsample_step_m=0)


def test_invalid_polygon_is_rejected_before_provider():
    module = importlib.import_module('backend.app.modules.land.datum')
    with pytest.raises(ValueError):
        module.DatumService(Provider()).compute(module.DatumContext(shape({'type':'Polygon','coordinates':[]})))


def test_explicit_settings_are_isolated_and_preserve_weighted_constant_elevation():
    module = importlib.import_module('backend.app.modules.land.datum')
    polygon = shape(FIXTURE['cases'][0]['parcel'])
    sparse = module.DatumCalculator(Provider().fetch, module.DatumSettings(edge_subsample=False, median_filter=False))
    dense = module.DatumCalculator(Provider().fetch)
    sparse_value, sparse_segments = sparse.parcel_datum_119(polygon)
    dense_value, dense_segments = dense.parcel_datum_119(polygon)
    assert sparse_value == pytest.approx(10)
    assert dense_value == pytest.approx(10)
    assert len(sparse_segments) == 4
    assert len(dense_segments) > 4
    assert dense._denoise_median_filter([10, 10, 100, 10, 10]) == [10]*5


def test_nonfinite_matching_length_samples_fail_closed():
    module = importlib.import_module('backend.app.modules.land.datum')
    class BadProvider(Provider):
        def fetch(self, points):
            return [float('nan')]*len(points)
    result = module.DatumService(BadProvider()).compute(module.DatumContext(shape(FIXTURE['cases'][0]['parcel'])))
    assert result.elevation_m is None
    assert result.elevation_source == 'failed'


def test_missing_optional_neighbor_preserves_parcel_and_safe_note():
    from backend.app.adapters.elevation import ElevationFetchError
    module = importlib.import_module('backend.app.modules.land.datum')
    class PartialProvider(Provider):
        calls = 0
        def fetch(self, points):
            self.calls += 1
            if self.calls > 1:
                raise ElevationFetchError('private provider URL')
            return super().fetch(points)
    parcel = shape(FIXTURE['cases'][0]['parcel'])
    result = module.DatumService(PartialProvider()).compute(module.DatumContext(parcel, neighbor_parcel_wgs=parcel))
    assert result.elevation_m == pytest.approx(10)
    assert result.neighbor_datum_m is None
    assert result.notes == ['neighbor parcel datum unavailable']


def test_provider_provenance_is_preserved_without_mutable_aliasing():
    module = importlib.import_module('backend.app.modules.land.datum')
    provider = Provider()
    provider.provenance = {'actual_provider':'fixture','providers':['fixture'],'fallback_used':True}
    context = module.DatumContext(shape(FIXTURE['cases'][0]['parcel']))
    result = module.DatumService(provider).compute(context)
    assert result.provenance == provider.provenance
    result.provenance['providers'].append('changed')
    assert provider.provenance['providers'] == ['fixture']
    provider.bad = []
    failed = module.DatumService(provider).compute(context)
    assert failed.elevation_m is None
    assert failed.elevation_source == 'failed'
    assert failed.provenance == provider.provenance


def test_zero_length_road_keeps_parcel_instead_of_fake_zero():
    from shapely.geometry import LineString
    module = importlib.import_module('backend.app.modules.land.datum')
    parcel = shape(FIXTURE['cases'][0]['parcel'])
    result = module.DatumService(Provider()).compute(module.DatumContext(parcel,
        road_centerline_wgs=LineString([(127,37),(127,37)]),apply_road_datum=True))
    assert result.elevation_m == pytest.approx(10)
    assert result.road_datum_m is None
    assert result.notes == ['road centerline datum unavailable']


@pytest.mark.parametrize('method', ['parcel_datum_119','road_datum_119','_boundary_elevation_profile'])
def test_large_sampling_geometry_fails_before_fetch(method):
    from shapely.geometry import box, LineString
    from backend.app.adapters.elevation import ElevationFetchError
    module = importlib.import_module('backend.app.modules.land.datum')
    def fetch(points):
        pytest.fail('Oversized geometry must fail before provider access')
    calculator = module.DatumCalculator(fetch)
    geometry = LineString([(127,37),(129,39)]) if method=='road_datum_119' else box(127,37,129,39)
    with pytest.raises(ElevationFetchError,match='budget'):
        getattr(calculator,method)(geometry)


def test_extreme_finite_elevation_cannot_allocate_unbounded_bands():
    from backend.app.adapters.elevation import ElevationFetchError
    module = importlib.import_module('backend.app.modules.land.datum')
    calculator = module.DatumCalculator(lambda points:[1e20 if i%2 else 0 for i in range(len(points))])
    with pytest.raises(ElevationFetchError,match='budget'):
        calculator.split_3m_segments(shape(FIXTURE['cases'][0]['parcel']))
