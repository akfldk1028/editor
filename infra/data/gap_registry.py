"""Unified, evidence-linked data gaps; disappearing from an audit never means resolved."""
import argparse,hashlib,json,time
from pathlib import Path
from release_store import atomic_json,encoded,locked,read_json,digest
from audit_building_regions import incomplete_region,audit

def reconcile(previous,observed):
    rows={row['id']:{**row,'state':'not_rechecked','previousState':row['state']} for row in previous}
    for row in observed:
        old=rows.get(row['id'],{})
        rows[row['id']]={**row,'firstObservedAt':old.get('firstObservedAt',time.time()),'lastObservedAt':time.time()}
    return sorted(rows.values(),key=lambda row:row['id'])

def original_status(row,rechecked):
    if not rechecked:return 'historical_omission_not_reverified'
    if rechecked.get('state')=='received':
        if str(row.get('year',''))[:4] in set(map(str,rechecked.get('downloadedYears',[]))):
            return 'same_year_received_edition_unverified'
        return 'other_edition_received_ground_pending'
    if rechecked.get('state')=='now_listed_not_downloaded':return 'listed_order_pending'
    return 'historical_omission_not_reverified'

def collect(root,originals):
    observed=[];sources=[]
    def source(path):
        sources.append({'path':str(path),'sha256':digest(path)})
        return read_json(path)
    coverage_path=root/'r2-migration/national-region-coverage-audit.json'
    catalog_path=root/'world-buildings/catalog.json'
    if catalog_path.exists():
        catalog_revision=digest(catalog_path)
        old_coverage=read_json(coverage_path) if coverage_path.exists() else {}
        if old_coverage.get('catalogRevision')!=catalog_revision or old_coverage.get('auditVersion')!=2:
            version=read_json(catalog_path)['source'].rstrip('/').split('/')[-2]
            atomic_json(coverage_path,audit(root/'tiles/buildings'/version/'buildings.pmtiles',catalog_path))
    if coverage_path.exists():
        coverage=source(coverage_path)
        outside=set(coverage.get('outsidePublicationBounds',[]))
        for key in coverage['sourceWithoutPreparedRegion']:observed.append({'id':'mesh:'+key,'state':'outside_publication_bounds' if key in outside else 'missing_prebuilt_region','tile':key,'evidenceSHA256':sources[-1]['sha256']})
    if catalog_path.exists():
        catalog=source(catalog_path)
        for row in catalog['regions']:
            if incomplete_region(row):
                key=f"{row['z']}/{row['x']}/{row['y']}"
                observed.append({'id':'partial:'+key,'state':'partial_prebuilt_region','tile':key,'evidenceSHA256':sources[-1]['sha256']})
    provider_path=originals/'catalogued-without-zip-dxf.json'
    recheck_path=root/'management/national-source-expansion/original-receipt-reclassification.json'
    rechecked={};recheck_sha=None
    if recheck_path.exists():
        rechecked={str(row['sheet']):row for row in source(recheck_path)['rows']}
        recheck_sha=sources[-1]['sha256']
    if provider_path.exists():
        for row in source(provider_path):
            identity='ngii:'+':'.join(str(row.get(key,'')) for key in ['scale','sheet','year'])
            current=rechecked.get(str(row['sheet']))
            observed.append({'id':identity,'state':original_status(row,current),'provider':'NGII','sheet':row['sheet'],'scale':row.get('scale'),'edition':row.get('year'),'evidenceSHA256':sources[-1]['sha256'],'recheckSHA256':recheck_sha,'receiptPaths':current.get('receiptPaths',[]) if current else [],'cause':'historical_package_omission_does_not_establish_unavailability'})
    terrain_path=root/'terrain-archive-national/island-qa-and-gap.json'
    if terrain_path.exists():
        row=source(terrain_path)['sourceGap']
        if row['terrainFiniteSamples']==0:
            observed.append({'id':'terrain-point:'+','.join(map(str,row['point'])),'state':'source_nodata','point':row['point'],'name':row['name'],'evidenceSHA256':sources[-1]['sha256']})
    with locked(root):
        path=root/'management/gaps/unified-current.json';old=read_json(path) if path.exists() else None
        if old and old.get('schema')=='ace-data-gap-registry-v2' and old['sources']==sources:return {'snapshot':hashlib.sha256(encoded(old)).hexdigest(),'counts':old['counts'],'issues':len(old['issues']),'reused':True}
        previous=old['issues'] if old else []
        issues=reconcile(previous,observed);counts={}
        for row in issues:counts[row['state']]=counts.get(row['state'],0)+1
        document={'schema':'ace-data-gap-registry-v2','observedAt':time.time(),'sources':sources,'counts':counts,'issues':issues,'complete':False}
        identity=hashlib.sha256(encoded(document)).hexdigest()
        atomic_json(root/'management/gaps/snapshots'/f'{identity}.json',document);atomic_json(path,document)
        return {'snapshot':identity,'counts':counts,'issues':len(issues)}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--data-root',type=Path,required=True);p.add_argument('--ngii-originals',type=Path,required=True);a=p.parse_args()
    print(json.dumps(collect(a.data_root,a.ngii_originals)))
