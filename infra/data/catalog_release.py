"""Build small spatial catalogs and a referenced-file upload plan, without copying meshes."""
import argparse,hashlib,json,math,os,time,stat
from pathlib import Path,PurePosixPath
from urllib.parse import unquote,urlsplit

def write_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    raw=json.dumps(value,ensure_ascii=False,separators=(',',':')).encode()
    if path.exists():
        if path.read_bytes()!=raw:raise ValueError('Immutable catalog version collision')
        return len(raw)
    temp=path.with_suffix(path.suffix+'.tmp');temp.write_bytes(raw);temp.replace(path);return len(raw)

def bounds(z,x,y):
    n=2**z;lat=lambda v:math.degrees(math.atan(math.sinh(math.pi*(1-2*v/n))))
    return [x/n*360-180,lat(y+1),(x+1)/n*360-180,lat(y)]

def build(catalog_path,public_root,output,*,publish=False):
    raw=catalog_path.read_bytes();revision=hashlib.sha256(raw).hexdigest();catalog=json.loads(raw)
    groups={};assets={};seen=set();root=public_root/'world-buildings'
    def asset(uri):
        parsed=urlsplit(uri)
        if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:raise ValueError('Expected a local catalog dependency')
        relative=PurePosixPath(unquote(parsed.path).removeprefix('/world-buildings/'))
        if relative.is_absolute() or '..' in relative.parts or relative.suffix not in ('.json','.b3dm','.glb','.gltf','.bin'):raise ValueError('Invalid catalog dependency')
        file=root/str(relative)
        key=relative.as_posix()
        if key in assets:return file,key
        info=file.stat()
        if not stat.S_ISREG(info.st_mode):raise FileNotFoundError(f'Missing catalog dependency: {relative}')
        assets[key]={'key':key,'bytes':info.st_size}
        return file,key
    def tileset(uri):
        file,key=asset(uri)
        if key in seen:return
        seen.add(key);tree=json.loads(file.read_text(encoding='utf-8'))
        def visit(node):
            for content in [node.get('content'),*node.get('contents',[])]:
                if not content:continue
                ref=content.get('uri') or content.get('url')
                if not ref:continue
                path=PurePosixPath(key).parent/ref
                if path.suffix=='.json':tileset('/world-buildings/'+path.as_posix())
                else:asset('/world-buildings/'+path.as_posix())
            for child in node.get('children',[]):visit(child)
        visit(tree['root'])
        provenance=file.parent/'ground-source.json'
        if provenance.is_file():asset('/world-buildings/'+(PurePosixPath(key).parent/'ground-source.json').as_posix())
    for number,region in enumerate(catalog['regions'],1):
        if region['z']<10:raise ValueError('Catalog region is coarser than shard grid')
        shift=region['z']-10;key=(region['x']>>shift,region['y']>>shift)
        groups.setdefault(key,[]).append(region)
        tileset(region['url']);asset(region['footprints'])
        if number%1000==0:print(f'Validated {number}/{len(catalog["regions"])} regions, {len(assets)} files',flush=True)
    folder=output/'catalogs'/revision;shards=[]
    for (x,y),regions in sorted(groups.items()):
        name=f'10-{x}-{y}.json';size=write_json(folder/name,{'schema':'world-buildings/shard-v1','revision':revision,'regions':regions})
        shards.append({'key':f'10/{x}/{y}','bounds':bounds(10,x,y),'href':f'catalogs/{revision}/{name}','regions':len(regions),'bytes':size})
    index={'schema':'world-buildings/catalog-index-v1','revision':revision,'source':catalog['source'],'shardZoom':10,'shards':shards}
    index_size=write_json(folder/'index.json',index)
    latest={'schema':'world-buildings/latest-v1','revision':revision,'source':catalog['source'],'index':f'catalogs/{revision}/index.json'}
    if hashlib.sha256(catalog_path.read_bytes()).hexdigest()!=revision:raise ValueError('Catalog changed during preparation')
    report={'revision':revision,'regions':len(catalog['regions']),'shards':len(shards),'indexBytes':index_size,'largestShardBytes':max(s['bytes'] for s in shards),'assetFiles':len(assets),'assetBytes':sum(f['bytes'] for f in assets.values()),'latest':latest,'assets':list(assets.values())}
    write_json(output.parent/'management/catalog-plans'/f'{revision}.json',report)
    if publish:
        temp=output/'latest.next.json';temp.write_text(json.dumps(latest,separators=(',',':')),encoding='utf-8')
        for attempt in range(30):
            try:temp.replace(output/'latest.json');break
            except PermissionError:
                if attempt==29:raise
                time.sleep(.1)
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--catalog',type=Path,required=True);p.add_argument('--public',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--publish-local',action='store_true');a=p.parse_args()
    result=build(a.catalog,a.public,a.output,publish=a.publish_local);print(json.dumps({k:v for k,v in result.items() if k!='assets'}))
