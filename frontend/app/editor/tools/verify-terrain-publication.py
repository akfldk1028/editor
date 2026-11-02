"""Verify packed PMTiles against checkpoints and the actual HTTP range route."""
import argparse,gzip,hashlib,json,math,sqlite3
from pathlib import Path
import httpx,numpy as np
from pmtiles.reader import Reader,MmapSource
from pmtiles.tile import zxy_to_tileid,tileid_to_zxy
p=argparse.ArgumentParser();p.add_argument('--work',type=Path,required=True);p.add_argument('--public',type=Path,required=True);p.add_argument('--base-url',default='http://127.0.0.1:3003');a=p.parse_args()
receipt=json.loads((a.work/'archive-receipt.json').read_text(encoding='utf-8'));path=a.public/'world-terrain'/receipt['url'].rsplit('/',1)[-1]
with path.open('rb') as file:checksum=hashlib.file_digest(file,'sha256').hexdigest()
assert checksum==receipt['sha256'] and path.stat().st_size==receipt['bytes']
db=sqlite3.connect(str(next(a.work.glob('terrain-*.sqlite'))));checked=0;cities=[]
with path.open('rb') as file:
    reader=Reader(MmapSource(file));assert reader.metadata()==receipt['metadata']
    points=json.loads((a.work/'detail-points.json').read_text(encoding='utf-8'))
    ids={row[0] for row in db.execute('SELECT id FROM tiles ORDER BY id LIMIT 20')}
    for row in points[::max(1,len(points)//100)]:
        lon,lat=row['point'];w=180/2**20;ids.add(zxy_to_tileid(21,math.floor((lon+180)/w),math.floor((90-lat)/w)))
    for tileid in ids:
        expected=db.execute('SELECT data FROM tiles WHERE id=?',(tileid,)).fetchone()
        if expected:
            assert reader.get(*tileid_to_zxy(tileid))==expected[0];checked+=1
    for name,lon,lat in [('Gosan',127.1081,37.73002),('Seoul',126.978,37.5665),('Daegu',128.6014,35.8714),('Busan',129.0756,35.1796),('Jeju',126.5312,33.4996)]:
        w=180/2**15;tile=reader.get(16,math.floor((lon+180)/w),math.floor((90-lat)/w));grid=np.frombuffer(gzip.decompress(tile),dtype='<f4',offset=8) if tile else np.array([])
        cities.append({'name':name,'validSamples':int(np.isfinite(grid).sum()),'totalSamples':len(grid)})
with httpx.Client(base_url=a.base_url,timeout=30,trust_env=False) as client:
    response=client.get(receipt['url'],headers={'Range':'bytes=0-126'});assert response.status_code==206 and len(response.content)==127 and response.content[:7]==b'PMTiles'
    assert response.headers['content-range']==f"bytes 0-126/{receipt['bytes']}"
report={'archive':str(path),'sha256':checksum,'bytes':receipt['bytes'],'tiles':receipt['tiles'],'packedTilesCompared':checked,'httpStatus':response.status_code,'httpRange':response.headers['content-range'],'citySamples':cities}
(a.work/'publication-verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))
