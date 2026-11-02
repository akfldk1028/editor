"""Refresh the private storage registry without relocating or deleting source data."""
import argparse,json,time
from pathlib import Path
from release_store import atomic_json,read_json

ROLES={
 'copernicus-gap-reference':('reference','Reference elevation only; not equivalent to precise source terrain'),
 'ngii-ground-gap-sources':('source','Original supporting ground files'),
 'ngii-original-batch':('source','NGII originals and provider acquisition evidence'),
 'terrain-archive-focus':('work','Retained regional staging/checkpoint files'),
 'terrain-archive-national':('work','Nationwide checkpoints and validation evidence'),
 'r2-migration':('audit','Inventory, copy receipts and legacy backups; never public'),
 'management':('management','Private receipts, gap registry, history, locks and staging'),
 'releases':('publication','Immutable public release manifests and current pointer'),
 'tiles':('publication','Versioned building PMTiles'),
 'world-buildings':('publication','Immutable meshes and spatial catalogs; mutable writer catalog'),
 'world-terrain':('publication','Immutable terrain archives; mutable candidate pointer'),
 'processed':('derived','Processed source-job exports; raw inputs remain external'),
}

def status(root,dem,source_data):
    current=root/'releases/current.json';gaps=root/'management/gaps/unified-current.json'
    datasets=[{'key':p.name,'path':str(p),'role':ROLES.get(p.name,('unclassified','Needs review'))[0],'description':ROLES.get(p.name,('unclassified','Needs review'))[1]} for p in sorted(root.iterdir()) if p.is_dir()]
    result={'schema':'ace-storage-registry-v1','observedAt':time.time(),'dataRoot':str(root),'datasets':datasets,
      'externalInputs':[{'key':'dem','path':str(dem),'exists':dem.exists(),'role':'source-and-work'},{'key':'legacy-source-data','path':str(source_data),'exists':source_data.exists(),'role':'source'}],
      'activeRelease':read_json(current).get('releaseId') if current.exists() else None,'gapCounts':read_json(gaps)['counts'] if gaps.exists() else {},
      'unclassifiedDirectories':[d['key'] for d in datasets if d['role']=='unclassified'],'originalDeletionAuthorized':False,'r2State':'deferred_by_user'}
    atomic_json(root/'management/storage-registry.json',result);return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--data-root',type=Path,required=True);p.add_argument('--dem-root',type=Path,required=True);p.add_argument('--source-data-root',type=Path,required=True);a=p.parse_args()
    result=status(a.data_root,a.dem_root,a.source_data_root)
    print(json.dumps({'datasets':len(result['datasets']),'unclassified':result['unclassifiedDirectories'],'activeRelease':result['activeRelease'],'gapCounts':result['gapCounts']}))
