import asyncio
from datetime import datetime, timezone

from backend.app.modules.land.repository import LandRepository

PNU = '1168011200101280003'


def success():
    return {'success': True, 'pnu': PNU, 'zones': ['제2종일반주거지역'],
            'land_area_m2': 300.0, 'official_land_price': 1200,
            'land_use_situation': '대', 'source': 'vworld', 'zones_fetched': True}


class Provider:
    def __init__(self, result):
        self.result = result
    async def fetch(self, pnu):
        assert pnu == PNU
        return self.result


def lookup(provider, repo):
    from backend.app.modules.land.attributes import LandAttributes
    return asyncio.run(LandAttributes(provider, repo).get(PNU))


def test_live_result_is_cached_and_survives_reopen(tmp_path):
    repo = LandRepository(tmp_path)
    value = lookup(Provider(success()), repo)
    assert value['success'] is True
    assert value['cache']['stale'] is False
    record = LandRepository(tmp_path).get_land_cache(PNU)
    assert record['result']['zones'] == success()['zones']
    assert datetime.fromisoformat(record['fetched_at']).tzinfo == timezone.utc


def test_only_total_provider_failure_uses_cache_with_explicit_age(tmp_path):
    repo = LandRepository(tmp_path)
    lookup(Provider(success()), repo)
    failed = dict(success(), success=False, zones=[], zones_fetched=False,
                  source='unavailable', errors=['provider unavailable'])
    result = lookup(Provider(failed), repo)
    assert result['zones'] == success()['zones']
    assert result['cache']['stale'] is True
    assert result['cache']['fetched_at']
    assert result['errors'] == ['provider unavailable']
    partial = dict(failed, success=True, source='vworld', land_area_m2=500)
    result = lookup(Provider(partial), repo)
    assert result['zones'] == []
    assert result['land_area_m2'] == 500
    assert result['cache']['stale'] is False


def test_cache_failure_keeps_live_data_and_reports_unsaved(tmp_path):
    class Broken:
        def put_land_cache(self, *args):
            raise OSError('private path')
    value = lookup(Provider(success()), Broken())
    assert value['success'] is True
    assert value['cache']['saved'] is False
    assert 'private path' not in str(value)


def test_bad_cache_identity_is_not_accepted(tmp_path):
    import pytest
    repo = LandRepository(tmp_path)
    with pytest.raises(ValueError):
        repo.put_land_cache('1111010100100010000', success())
    with pytest.raises(ValueError):
        repo.put_land_cache(PNU, dict(success(), success=False))


def test_schema_upgrade_preserves_analysis_rows(tmp_path):
    import sqlite3
    repo = LandRepository(tmp_path)
    identifier = repo.save({'input_type': 'raw'}, {'kept': True}, 1)
    with sqlite3.connect(repo.path) as db:
        db.execute('DROP TABLE IF EXISTS land_cache')
        for table in ('legacy_queries', 'legacy_results', 'legacy_sources', 'history_imports'):
            db.execute('DROP TABLE ' + table)
        db.execute('PRAGMA user_version=1')
    lookup(Provider(success()), LandRepository(tmp_path))
    assert repo.get(identifier)['result'] == {'kept': True}
    assert repo.stats()['total_queries'] == 1
