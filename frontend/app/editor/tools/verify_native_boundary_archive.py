"""Check every classified native boundary against its immutable packed payload."""
import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from pmtiles.reader import Reader,MmapSource
from pmtiles.tile import tileid_to_zxy,zxy_to_tileid


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--work',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    receipt=json.loads((a.work/'archive-receipt.json').read_text(encoding='utf8'))
    archive=a.output/Path(receipt['url']).name
    with archive.open('rb') as f:
        assert hashlib.file_digest(f,'sha256').hexdigest()==receipt['sha256']
    patches=sqlite3.connect((a.work/'native-boundary-patches.sqlite').resolve().as_uri()+'?mode=ro',uri=True)
    checked=0;added_checked=0
    extension_path=a.work/'detail-extension.json'
    extension=json.loads(extension_path.read_text(encoding='utf8')) if extension_path.exists() else None
    with archive.open('rb') as f:
        reader=Reader(MmapSource(f))
        assert reader.metadata()==receipt['metadata']
        for tileid,data in patches.execute('SELECT id,data FROM classified WHERE boundary=1 ORDER BY id'):
            assert reader.get(*tileid_to_zxy(tileid))==data, f'Boundary payload mismatch at {tileid}'
            checked+=1
        if extension:
            database=a.work/('terrain-'+receipt['vrt_sha256'][:16]+'.sqlite')
            checkpoint=sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True)
            for level,x,y in extension['keys']:
                tileid=zxy_to_tileid(level+1,x,y)
                expected=checkpoint.execute('SELECT data FROM tiles WHERE id=?',(tileid,)).fetchone()
                assert expected and reader.get(*tileid_to_zxy(tileid))==expected[0],f'Added detail payload mismatch at {tileid}'
                added_checked+=1
    assert checked==receipt['metadata']['nativeBoundaryPolicy']['boundaryTiles']
    report=dict(archiveSHA256=receipt['sha256'],boundaryTilesCompared=checked,
                checkedVertices=checked*1089,includingNoDataMask=True,addedDetailTilesCompared=added_checked)
    (a.work/'native-boundary-packed-verification.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps(report))


if __name__=='__main__':main()
