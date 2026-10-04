import hashlib
import json
from pathlib import Path

import pytest

from backend.app.modules.land.repository import LandRepository

PNU='1168011200101280003'
STAMP='2026-01-01T00:00:00+00:00'


def sources(tmp_path):
    land=tmp_path/'land';zone=tmp_path/'zone';land.mkdir();zone.mkdir()
    result={'pnu':PNU,'success':True,'source':'vworld','zones':['zone'],
            'land_area_m2':100,'official_land_price':200,'land_use_situation':'land'}
    (land/f'{PNU}.json').write_text(json.dumps({'fetched_at':STAMP,'result':result}),encoding='utf8')
    bounds=[127.,37.,127.1,37.1]
    oldkey=hashlib.sha256(('LT_C_UQ111|'+','.join(f'{n:.6f}' for n in bounds)).encode()).hexdigest()[:16]
    features=[{'type':'Feature','geometry':{'type':'Polygon','coordinates':[[[127,37],[127.1,37],[127.1,37.1],[127,37.1],[127,37]]]},'properties':{'uname':'zone'}}]
    (zone/f'{oldkey}.json').write_text(json.dumps({'fetched_at':STAMP,'bounds':bounds,'layer':'LT_C_UQ111','features':features}),encoding='utf8')
    key=hashlib.sha256(json.dumps(['LT_C_UQ111',bounds]).encode()).hexdigest()
    return land,zone,result,key


def test_dry_run_never_creates_destination_and_import_preserves_time(tmp_path):
    from backend.app.modules.land.cache_import import import_caches
    land,zone,result,key=sources(tmp_path);repo=LandRepository(tmp_path/'destination')
    report=import_caches(repo,land,zone)
    assert report['valid'] and report['land']['insert']==report['zone']['insert']==1
    assert not repo.path.parent.exists()
    report=import_caches(repo,land,zone,dry_run=False)
    assert report['land']['imported']==report['zone']['imported']==1
    assert repo.get_land_cache(PNU)=={'result':result,'fetched_at':STAMP}
    assert repo.get_zone_cache(key)['fetched_at']==STAMP
    again=import_caches(repo,land,zone,dry_run=False)
    assert again['land']['skip_newer']==again['zone']['skip_newer']==1


@pytest.mark.parametrize('bad', ['identity','nan','duplicate','timestamp','zone_geometry','zone_key'])
def test_one_invalid_record_rejects_entire_selection_without_transaction(tmp_path,bad):
    from backend.app.modules.land.cache_import import import_caches
    land,zone,_,_=sources(tmp_path);path=land/f'{PNU}.json'
    payload=json.loads(path.read_text())
    if bad=='identity':payload['result']['pnu']='1168011200101280004'
    if bad=='nan':payload['result']['land_area_m2']=float('nan')
    if bad=='timestamp':payload['fetched_at']='2026-01-01'
    path.write_text(json.dumps(payload),encoding='utf8')
    if bad=='duplicate':path.write_text('{"result":1,"result":2}',encoding='utf8')
    if bad=='zone_geometry':
        zp=next(zone.glob('*.json'));z=json.loads(zp.read_text());z['features'][0]['geometry']['coordinates'][0][0]=[True,37];zp.write_text(json.dumps(z))
    if bad=='zone_key':next(zone.glob('*.json')).rename(zone/'wrong.json')
    repo=LandRepository(tmp_path/'destination')
    report=import_caches(repo,land,zone,dry_run=False)
    assert not report['valid'] and report['rejected']
    assert report['land']['imported']==report['zone']['imported']==0
    assert not repo.path.parent.exists()


def test_newer_destination_is_not_overwritten(tmp_path):
    from backend.app.modules.land.cache_import import import_caches
    land,zone,result,_=sources(tmp_path);repo=LandRepository(tmp_path/'destination')
    result['land_area_m2']=300;repo.put_land_cache(PNU,result)
    report=import_caches(repo,land,zone,dry_run=False)
    assert report['land']['skip_newer']==1
    assert repo.get_land_cache(PNU)['result']['land_area_m2']==300


def test_import_updates_older_cache_and_rolls_back_both_kinds_on_sql_failure(tmp_path):
    import sqlite3
    from backend.app.modules.land.cache_import import import_caches
    land,zone,result,_=sources(tmp_path);repo=LandRepository(tmp_path/'destination')
    repo.put_land_cache(PNU,result)
    with repo._transaction() as db:
        db.execute('UPDATE land_cache SET fetched_at=?',('2020-01-01T00:00:00+00:00',))
        db.execute("CREATE TRIGGER reject_zone BEFORE INSERT ON zone_cache BEGIN SELECT RAISE(ABORT,'fixture'); END")
    with pytest.raises(sqlite3.IntegrityError):
        import_caches(repo,land,zone,dry_run=False)
    assert repo.get_land_cache(PNU)['fetched_at']=='2020-01-01T00:00:00+00:00'
    with repo._transaction() as db:
        db.execute('DROP TRIGGER reject_zone')
    report=import_caches(repo,land,zone,dry_run=False)
    assert report['land']['update']==1
    assert repo.get_land_cache(PNU)['fetched_at']==STAMP


def test_zone_layer_topology_is_preserved_without_parcel_repair(tmp_path):
    from backend.app.modules.land.cache_import import import_caches
    land,zone,_,key=sources(tmp_path);path=next(zone.glob('*.json'))
    value=json.loads(path.read_text())
    value['features'][0]['geometry']['coordinates']=[[[127,37],[127.1,37.1],[127.1,37],[127,37.1],[127,37]]]
    path.write_text(json.dumps(value),encoding='utf8')
    repo=LandRepository(tmp_path/'destination')
    report=import_caches(repo,land,zone,dry_run=False)
    assert report['valid']
    assert repo.get_zone_cache(key)['features']==value['features']
