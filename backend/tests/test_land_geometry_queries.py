import asyncio
import pytest
from backend.app.modules.land.vworld.geometry import GeometryProviderUnavailable
from backend.app.modules.land.geometry_queries import GeometryQueries
from backend.app.modules.land.repository import LandRepository

PARCEL = {'type':'Polygon','coordinates':[[[127,37],[127.001,37],[127.001,37.001],[127,37.001],[127,37]]]}
FEATURE = {'type':'Feature','properties':{'uname':'제2종일반주거지역'},'geometry':PARCEL}


class Provider:
    def __init__(self, failure=None):
        self.failure = failure
    async def zone_features(self, geometry):
        if self.failure is not None:
            raise GeometryProviderUnavailable('fixture outage',cache_allowed=self.failure)
        return [FEATURE]
    async def cadastral_features(self, geometry):
        if self.failure is not None:
            raise GeometryProviderUnavailable('fixture outage')
        return []


def test_zone_cache_fallback_is_visible_and_only_used_for_transport_outage(tmp_path):
    repo = LandRepository(tmp_path)
    first, errors = asyncio.run(GeometryQueries(Provider(),repo).split(PARCEL))
    assert first['제2종일반주거지역'] > 0
    assert errors == []
    cached, errors = asyncio.run(GeometryQueries(Provider(True),LandRepository(tmp_path)).split(PARCEL))
    assert cached == first
    assert len(errors) == 1 and 'cached' in errors[0]
    assert asyncio.run(GeometryQueries(Provider(False),repo).split(PARCEL)) == (None,['Zone area split unavailable'])


def test_uncached_failure_is_not_an_invented_split(tmp_path):
    assert asyncio.run(GeometryQueries(Provider(True),LandRepository(tmp_path)).split(PARCEL))[0] is None


def test_empty_neighbor_result_and_failed_provider_remain_distinct():
    assert asyncio.run(GeometryQueries(Provider()).frontages(PARCEL)) == ([],[],[])
    assert asyncio.run(GeometryQueries(Provider(True)).frontages(PARCEL))[2]


def test_broken_cache_cannot_destroy_live_geometry():
    class Broken:
        def put_zone_cache(self,*args):
            raise OSError('private path')
    value, errors = asyncio.run(GeometryQueries(Provider(),Broken()).split(PARCEL))
    assert value['제2종일반주거지역'] > 0
    assert errors == []
