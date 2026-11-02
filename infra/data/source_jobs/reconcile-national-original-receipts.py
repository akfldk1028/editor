"""Reclassify historical package omissions using current lists and verified receipts."""
import hashlib
import json
from pathlib import Path
import re
import time
import source_job_paths as sjp

root=sjp.DATA_ROOT/'management/national-source-expansion'
historical=json.loads((sjp.NGII_ORIGINAL_ROOT/'catalogued-without-zip-dxf.json').read_text(encoding='utf-8'))
ids={str(row['sheet']) for row in historical}
listed={str(row['num']) for row in json.loads((root/'national-catalogue.json').read_text(encoding='utf-8'))}
proof={}
folders=[sjp.NGII_ORIGINAL_ROOT/'files',root/'files',root/'individual-gimpo/files',
         root/'individual-old-missing/files',root/'individual-priority-gap/files',
         root/'individual-critical-retry/files']
for folder in folders:
    for receipt in folder.glob('*.receipt.json'):
        match=re.search(r'_(\d{8,9})_(\d{4})_',receipt.name)
        if not match or match[1] not in ids:continue
        item=json.loads(receipt.read_text(encoding='utf-8'));target=folder/item['name']
        if target.suffix.lower() not in {'.zip','.dxf','.ngi'} or not target.exists():continue
        if target.stat().st_size!=item['bytes']:continue
        with target.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        if digest!=item['sha256']:continue
        proof.setdefault(match[1],[]).append(dict(receiptPath=str(receipt),year=match[2]))
rows=[]
for sheet in sorted(ids):
    receipts=proof.get(sheet,[])
    rows.append(dict(sheet=sheet,state='received' if receipts else 'now_listed_not_downloaded' if sheet in listed else 'not_reverified',
        receiptPaths=[r['receiptPath'] for r in receipts],downloadedYears=sorted({r['year'] for r in receipts})))
value=dict(at=time.time(),source='Historical package omissions rechecked against provider municipality search and local SHA-256 receipts',
    rows=rows,counts={state:sum(r['state']==state for r in rows) for state in ['received','now_listed_not_downloaded','not_reverified']},
    limitation='Received originals do not establish usable terrain, TIN support, or resolved building elevations.')
target=root/'original-receipt-reclassification.json';temporary=target.with_suffix('.tmp')
temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(target)
print(json.dumps(value['counts']))
