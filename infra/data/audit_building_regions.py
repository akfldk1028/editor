"""Compare source archive tile addresses with prepared regions; not building-level completeness."""
import argparse,json,hashlib,math
from pathlib import Path
from pmtiles.reader import MmapSource,deserialize_header,deserialize_directory,tileid_to_zxy

def within_publication_bounds(key):
    z,x,y=map(int,key.split('/'));n=2**z
    latitude=lambda v:math.degrees(math.atan(math.sinh(math.pi*(1-2*v/n))))
    west=x/n*360-180;east=(x+1)/n*360-180
    return west<=132.0 and east>=124.6 and latitude(y)>=33.1 and latitude(y+1)<=38.65

def incomplete_region(region):
    if region.get('partialCoverage'):return True
    if 'coverage' not in region:return False
    level=region['z']
    if level>16:return False
    scale=2**(16-level)
    expected={f"16/{region['x']*scale+x}/{region['y']*scale+y}" for x in range(scale) for y in range(scale)}
    return not expected.issubset(set(region['coverage']))

def audit(archive,catalog,*,rows=None):
    raw=catalog.read_bytes() if rows is None else None
    rows=json.loads(raw)['regions'] if raw is not None else rows
    prepared={f"{r['z']}/{r['x']}/{r['y']}" for r in rows}
    source=set()
    with archive.open('rb') as file:
        get=MmapSource(file);header=deserialize_header(get(0,127))
        def walk(offset,length):
            for item in deserialize_directory(get(offset,length)):
                if item.run_length:
                    for identity in range(item.tile_id,item.tile_id+item.run_length):
                        z,x,y=tileid_to_zxy(identity)
                        if z==14:source.add(f'{z}/{x}/{y}')
                else:walk(header['leaf_directory_offset']+item.offset,item.length)
        walk(header['root_offset'],header['root_length'])
    return {'auditVersion':2,'publicationBounds':[124.6,33.1,132.0,38.65],
            'outsidePublicationBounds':sorted(k for k in source-prepared if not within_publication_bounds(k)),
            'catalogRevision':hashlib.sha256(raw).hexdigest() if raw is not None else None,'sourceZ14Tiles':len(source),'preparedRegions':len(prepared),'matchingSourceRegions':len(source&prepared),
            'sourceWithoutPreparedRegion':sorted(source-prepared),'preparedWithoutSourceZ14':sorted(prepared-source),
            'partialRegions':sum(incomplete_region(r) for r in rows),
            'scope':'Tile-address audit only. A prepared region may have partial coverage; an absent region does not establish how many buildings or source height samples are missing.'}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--archive',type=Path,required=True);p.add_argument('--catalog',type=Path,required=True);p.add_argument('--report',type=Path,required=True);a=p.parse_args()
    result=audit(a.archive,a.catalog);a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({k:len(v) if isinstance(v,list) else v for k,v in result.items()}))
