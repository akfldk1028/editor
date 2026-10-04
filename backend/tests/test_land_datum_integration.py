from types import SimpleNamespace
import pytest
from backend.app.modules.regulations.setbacks import compute_setback_lines

PARCEL = {'type':'Polygon','coordinates':[[[127,37],[127.001,37],[127.001,37.001],[127,37.001],[127,37]]]}
RULES = {'sunlight_applies':True, 'sunlight_rules':[]}


class Service:
    def __init__(self, elevation=25, failed=False):
        self.elevation = elevation
        self.failed = failed
        self.context = None
    def compute(self, context):
        self.context = context
        return SimpleNamespace(elevation_m=None if self.failed else self.elevation,
            case=SimpleNamespace(value='flat'),basis='fixture',
            elevation_source='failed' if self.failed else 'fixture_dem',
            neighbor_avg_datum_m=None, notes=['unavailable'] if self.failed else [],
            provenance={'actual_provider':'fixture_dem'})


def test_datum_metadata_preserves_relative_envelope_geometry():
    baseline = compute_setback_lines(PARCEL, RULES)
    service = Service()
    result = compute_setback_lines(PARCEL,RULES,compute_datum=True,datum_service=service)
    assert result['datum_result']['elevation_m'] == 25
    envelope = result['sunlight_envelope']
    assert envelope['datum_elevation_m'] == 25
    assert envelope['elevation_source'] == 'fixture_dem'
    for key in ('walls','slanted_polygons'):
        assert envelope[key] == baseline['sunlight_envelope'][key]
    assert service.context.parcel_wgs.area > 0


def test_failed_datum_does_not_claim_zero_absolute_elevation():
    result = compute_setback_lines(PARCEL,RULES,compute_datum=True,datum_service=Service(failed=True))
    assert result['datum_result']['elevation_m'] is None
    assert result['datum_result']['elevation_source'] == 'failed'
    assert result['sunlight_envelope']['datum_elevation_m'] is None
    assert result['sunlight_envelope']['elevation_source'] == 'failed'
    assert result['sunlight_envelope']['walls']


def test_enabled_datum_requires_explicit_service():
    with pytest.raises(ValueError,match='service'):
        compute_setback_lines(PARCEL,RULES,compute_datum=True)


def test_datum_geometry_guard_preserves_relative_envelope():
    from shapely.geometry import Point, mapping
    from backend.app.modules.land.datum import DatumService
    class UnusedProvider:
        def fetch(self, points):
            pytest.fail('Oversized geometry must be rejected before elevation lookup')
    parcel = mapping(Point(127,37).buffer(.001, quad_segs=150))
    baseline = compute_setback_lines(parcel, RULES)
    result = compute_setback_lines(parcel, RULES, compute_datum=True,
        datum_service=DatumService(UnusedProvider()))
    assert result['datum_result']['elevation_m'] is None
    assert result['datum_result']['basis'] == 'datum_context_unavailable'
    assert result['sunlight_envelope']['walls'] == baseline['sunlight_envelope']['walls']


def test_primary_road_skips_invalid_zero_length_candidate():
    from backend.app.modules.land.datum.context_geometry import road_centerline
    valid = [[127,37],[127.001,37]]
    selected = road_centerline([
        {'roadCenterline':[[127,37],[127,37]],'roadWidthM':30},
        {'roadCenterline':valid,'roadWidthM':8}])
    assert list(selected.coords) == [tuple(point) for point in valid]
