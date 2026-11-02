"""Bind current local map publications and evidence into a verified, inactive release."""
import argparse,hashlib,json,re
from pathlib import Path
from release_store import read_json,seal,digest,atomic_json,encoded
from audit_building_regions import audit,incomplete_region

def immutable_json(path,value):
    if path.exists():
        if read_json(path)!=value:raise ValueError('Immutable evidence collision')
    else:atomic_json(path,value)

def prepare(root,terrain_work,*,reuse=True,catalog_path=None,catalog_pointer_path=None,terrain_pointer_path=None):
    current=root/'releases/current.json';predecessor=read_json(current)['releaseId'] if current.exists() else None
    catalog_root=root/'world-buildings';latest=read_json(catalog_pointer_path or catalog_root/'latest.json')
    revision=latest['revision']
    if not re.fullmatch('[a-f0-9]{64}',revision):raise ValueError('Invalid catalog revision')
    catalog_path=catalog_path or catalog_root/'catalog.json'
    catalog_bytes=catalog_path.read_bytes();catalog=json.loads(catalog_bytes)
    if hashlib.sha256(catalog_bytes).hexdigest()!=revision:raise ValueError('Catalog writer state does not match published snapshot')
    plan_path=root/'management/catalog-plans'/f'{revision}.json'
    if not plan_path.exists():plan_path=catalog_root/'catalogs'/revision/'upload-plan.json'
    plan=read_json(plan_path)
    if plan['latest']!=latest:raise ValueError('Catalog dependency plan mismatch')
    version=latest['source'].rstrip('/').split('/')[-2]
    if not re.fullmatch(r'\d{8}-[a-f0-9]{8}',version):raise ValueError('Invalid building archive version')
    archive=root/'tiles/buildings'/version/'buildings.pmtiles'
    terrain=read_json(terrain_pointer_path or root/'world-terrain/archive.json');receipt=read_json(terrain_work/'archive-receipt.json')
    validation=read_json(terrain_work/'publication-verification.json');heights=read_json(terrain_work/'height-verification.json')
    if terrain['sha256']!=receipt['sha256'] or validation['sha256']!=terrain['sha256']:raise ValueError('Terrain verification refers to another archive')
    if heights.get('sourceVrtSHA256')!=terrain['vrt_sha256'] or heights.get('terrainArchiveSHA256')!=terrain['sha256'] or heights.get('buildingCatalogSHA256')!=revision:raise ValueError('Height validation refers to another dataset version; rerun verification')
    if not heights.get('sourceFilesSHA256') or heights['sourceFilesSHA256']!=receipt['metadata'].get('sourceFilesSHA256'):raise ValueError('DEM rasters changed since terrain baking')
    if heights.get('missing') or heights['publishedBuildingDatumCheck']['compared']!=heights['publishedBuildingDatumCheck']['expected']:raise ValueError('Ground datum validation incomplete')
    if heights['absoluteErrorMetres']['maximum']>.5 or heights['publishedBuildingDatumCheck']['maximumAbsoluteErrorMetres']>.01:raise ValueError('Building/terrain height alignment exceeds publication tolerance')
    terrain_path=root/'world-terrain'/Path(terrain['url']).name
    if digest(terrain_path)!=terrain['sha256']:raise ValueError('Terrain archive hash mismatch')
    coverage=audit(archive,catalog_path,rows=catalog['regions'])
    evidence_values={'coverage.json':coverage,'archive-receipt.json':receipt,'publication-verification.json':validation,'height-verification.json':heights}
    snapshot=hashlib.sha256(encoded(evidence_values)).hexdigest()
    evidence=root/'management/evidence'/snapshot
    for name,value in evidence_values.items():immutable_json(evidence/name,value)
    # The ledger retains unresolved historical entries until positive evidence
    # establishes resolution; absence from a new report is not proof of repair.
    ledger_path=root/'management/gaps/current.json';previous=read_json(ledger_path) if ledger_path.exists() else {'issues':[]}
    issues={row['id']:{**row,'state':'not_rechecked'} for row in previous['issues']}
    coordinates={f"{r['z']}/{r['x']}/{r['y']}" for r in catalog['regions']}
    partial={f"{r['z']}/{r['x']}/{r['y']}" for r in catalog['regions'] if incomplete_region(r)}
    missing=set(coverage['sourceWithoutPreparedRegion'])
    for key in missing:issues['mesh:'+key]={'id':'mesh:'+key,'state':'missing_prebuilt_region','tile':key,'evidence':f'management/evidence/{snapshot}/coverage.json'}
    for key in partial:issues['partial:'+key]={'id':'partial:'+key,'state':'partial_prebuilt_region','tile':key,'evidence':f'management/evidence/{snapshot}/coverage.json'}
    for identity,row in issues.items():
        if row['state']=='not_rechecked' and row.get('tile') in coordinates and row['tile'] not in missing|partial:row['state']='resolved_in_catalog';row['resolvedRevision']=revision
    ledger={'schema':'ace-data-gaps-v1','catalogRevision':revision,'issues':list(issues.values()),'scope':'Mesh coverage; provider source availability and terrain NoData audits remain linked evidence, not silently resolved.'}
    ledger_id=hashlib.sha256(encoded(ledger)).hexdigest()
    immutable_json(root/'management/gaps'/f'{ledger_id}.json',ledger);atomic_json(ledger_path,ledger)
    files=[archive,root/'tiles/buildings'/version/'manifest.json',terrain_path]
    index=read_json(catalog_root/latest['index']);files.append(catalog_root/latest['index'])
    files.extend(catalog_root/s['href'] for s in index['shards'])
    files.extend(catalog_root/row['key'] for row in plan['assets'])
    files.extend(evidence/name for name in ['coverage.json','archive-receipt.json','publication-verification.json','height-verification.json'])
    files.append(root/'management/gaps'/f'{ledger_id}.json')
    public_catalog={**latest,'source':f'/api/map-data/buildings/{version}/buildings.pmtiles'}
    payload={'schema':'ace-map-release-v1','predecessorRelease':predecessor,'buildings':{'version':version,'href':public_catalog['source']},'buildingCatalog':public_catalog,'terrain':terrain,
             'groundValidation':{'compared':heights['publishedBuildingDatumCheck']['compared'],'sourceVrtSHA256':terrain['vrt_sha256']},
             'coverage':{'sourceTiles':coverage['sourceZ14Tiles'],'preparedCoordinates':coverage['preparedRegions'],'missingPreparedTiles':len(missing),'partialCoordinates':len(partial),'complete':False}}
    return seal(root,payload,files,reuse=reuse)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--data-root',type=Path,required=True);p.add_argument('--terrain-work',type=Path,required=True);p.add_argument('--rehash',action='store_true')
    p.add_argument('--catalog',type=Path);p.add_argument('--catalog-pointer',type=Path);p.add_argument('--terrain-pointer',type=Path);a=p.parse_args()
    result=prepare(a.data_root.resolve(),a.terrain_work.resolve(),reuse=not a.rehash,catalog_path=a.catalog,catalog_pointer_path=a.catalog_pointer,terrain_pointer_path=a.terrain_pointer);print(json.dumps(result))
