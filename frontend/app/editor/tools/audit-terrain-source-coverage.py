"""Reconcile the historical rectangle estimate against verified original geometry."""
import collections,json,re,time
from pathlib import Path
import numpy as np
from pyproj import Transformer
from scipy.spatial import cKDTree
root=Path('C:/Data/25_ACE/ngii-original-batch')
records=json.loads(Path('D:/Data/NGII_DEM/national-gap-exact-points.json').read_text(encoding='utf-8'))
ll=np.array([r['point'] for r in records]);x,y=Transformer.from_crs(4326,5179,always_xy=True).transform(ll[:,0],ll[:,1]);tree=cKDTree(np.column_stack([x,y]))
available=set()
for path in root.glob('*-manifest.json'):
    for f in json.loads(path.read_text(encoding='utf-8'))['files']:
        if not f['name'].endswith(('.zip','.dxf')):continue
        match=re.search(r'_(\d{8,9})_\d{4}_',f['name'])
        if match:available.add(match[1])
seen=set();inside=set();missing_sheets=[]
for path in root.glob('*-catalogue.json'):
    for row in json.loads(path.read_text(encoding='utf-8')):
        if row['sheet'] in seen or row.get('projection')!='GRS80' or int(row.get('scale') or 999999)>5000:continue
        seen.add(row['sheet']);a,b,c,d=[float(row[k]) for k in ['minx','miny','maxx','maxy']]
        if row['sheet'] not in available:
            missing_sheets.append({**row,'catalogue':path.name});continue
        indices=tree.query_ball_point([(a+c)/2,(b+d)/2],np.hypot(c-a,d-b)/2)
        inside.update(i for i in indices if a<=x[i]<=c and b<=y[i]<=d)
keys={records[i]['key'] for i in inside}
stage=json.loads((root/'terrain-stage-status.json').read_text(encoding='utf-8'))
verified={k for r in stage['results'].values() for k in r.get('verifiedKeys',[])}
receipt=json.loads((root/'terrain-install-receipt.json').read_text(encoding='utf-8'));installed=set(receipt['verifiedKeys'])
report={'at':time.time(),'historicalRectangleEstimate':len(keys),'verifiedOriginalGeometryInsideRectangles':len(keys&verified),
        'installedInsideRectangles':len(keys&installed),'notVerifiedInsideRectangles':len(keys-verified),
        'allInstalledVerified':len(installed),'installedOutsideHistoricalRectangles':len(installed-keys),
        'sourceFileStates':dict(collections.Counter(r['state'] for r in stage['results'].values())),
        'scope':'Verified contour/spot TIN plus valid 5m patch cells from the staging audit. Not-verified is not proof that a source cannot exist.',
        'unverifiedKeys':sorted(keys-verified)}
(root/'exact-coverage-reconciliation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
(root/'catalogued-without-zip-dxf.json').write_text(json.dumps(missing_sheets,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k!='unverifiedKeys'}))
