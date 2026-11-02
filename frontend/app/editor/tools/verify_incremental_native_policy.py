"""Verify all touched L20 native boundary payloads after an incremental bake."""
import argparse,gzip,json,sqlite3
from pathlib import Path
import rasterio
from pmtiles.tile import tileid_to_zxy,zxy_to_tileid
from native_terrain_boundary import native_tiles,provenance
from terrain_archive import encode_grid
from incremental_terrain_archive import sha,atomic_json


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--work',type=Path,required=True);p.add_argument('--dem',type=Path,required=True);a=p.parse_args()
    receipt=json.loads((a.work/'archive-receipt.json').read_text());meta=receipt['metadata'];assert meta['samplerSHA256']==provenance()['samplerSHA256'] and sha(a.dem)==meta['vrt_sha256']
    db=sqlite3.connect((a.work/('terrain-'+meta['vrt_sha256'][:16]+'.sqlite')).resolve().as_uri()+'?mode=ro',uri=True)
    lo,hi=zxy_to_tileid(21,0,0),zxy_to_tileid(22,0,0);keys=[]
    for (tileid,) in db.execute('SELECT id FROM incremental_affected WHERE id>=? AND id<?',(lo,hi)):
        z,x,y=tileid_to_zxy(tileid);keys.append((z-1,x,y))
    boundary=0;checked=0
    with rasterio.open(a.dem) as source:
        for level,x,y,is_boundary,grid in native_tiles(source,keys,validate=True):
            if is_boundary:
                expected=gzip.compress(encode_grid(grid),compresslevel=1,mtime=0)
                actual=db.execute('SELECT data FROM tiles WHERE id=?',(zxy_to_tileid(level+1,x,y),)).fetchone()
                assert actual and actual[0]==expected,('Native boundary mismatch',level,x,y)
                boundary+=1
            checked+=1
    report={'archiveSHA256':receipt['sha256'],'vrtSHA256':meta['vrt_sha256'],'affectedL20Tiles':checked,'nativeBoundaryTilesChecked':boundary,'nativeVerticesChecked':boundary*1089,'interiorGDALTiles':checked-boundary,'includingNoDataMask':True,'unchangedTileProof':receipt['verification']}
    atomic_json(a.work/'incremental-native-policy-verification.json',report);print(json.dumps(report))


if __name__=='__main__':main()
