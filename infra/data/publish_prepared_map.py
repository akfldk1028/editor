"""Validate staged local map data, seal one release, and optionally activate it."""
import argparse,json,subprocess,sys
from pathlib import Path
from catalog_release import build
from gap_registry import collect
from prepare_map_release import prepare
from release_store import activate,atomic_json
from storage_status import status
from audit_building_regions import audit

def run(root,terrain_work,dem,originals,source_data,*,activate_release=False,rehash=False):
    editor=Path(__file__).resolve().parents[2];tools=editor/'frontend/app/editor/tools'
    # Candidate pointers may change here; readers of current.json remain pinned
    # to the active release until every validation below has succeeded.
    catalog_release=build(root/'world-buildings/catalog.json',root,root/'world-buildings',publish=True)
    subprocess.run([sys.executable,str(tools/'verify-terrain-publication.py'),'--work',str(terrain_work),'--public',str(root)],check=True)
    subprocess.run([sys.executable,str(tools/'verify-terrain-archive.py'),'--work',str(terrain_work),'--dem',str(dem),'--points',str(terrain_work/'detail-points.json'),'--level','20','--buildings',str(root)],check=True)
    version=catalog_release['latest']['source'].rstrip('/').split('/')[-2]
    coverage=audit(root/'tiles/buildings'/version/'buildings.pmtiles',root/'world-buildings/catalog.json')
    atomic_json(root/'r2-migration/national-region-coverage-audit.json',coverage)
    collect(root,originals)
    release=prepare(root,terrain_work,reuse=not rehash)
    if activate_release:activate(root,release['releaseId'])
    status(root,dem.parent,source_data)
    return {'state':'active' if activate_release else 'prepared','releaseId':release['releaseId'],'files':release['fileCount'],'bytes':release['totalBytes'],'coverage':release['coverage']}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--data-root',type=Path,required=True);p.add_argument('--terrain-work',type=Path,required=True);p.add_argument('--dem',type=Path,required=True)
    p.add_argument('--ngii-originals',type=Path,required=True);p.add_argument('--source-data-root',type=Path,required=True);p.add_argument('--activate',action='store_true');p.add_argument('--rehash',action='store_true');a=p.parse_args()
    print(json.dumps(run(a.data_root,a.terrain_work,a.dem,a.ngii_originals,a.source_data,activate_release=a.activate,rehash=a.rehash)))
