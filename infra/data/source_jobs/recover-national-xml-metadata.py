"""Preserve repeatable, valid XML where provider manifest sizes are stale."""
import hashlib
import json
from pathlib import Path
import time
import xml.etree.ElementTree as ET
import httpx
import source_job_paths as sjp

root=sjp.DATA_ROOT/'management/national-source-expansion'
status=json.loads((root/'download-status.json').read_text(encoding='utf-8'))
failed={r['name'] for r in status['results'] if r['state']=='failed' and r.get('errorType')=='ValueError' and r['name'].endswith('.xml')}
entries={}
for manifest in root.glob('[0-9][0-9][0-9][0-9][0-9]-manifest.json'):
    for item in json.loads(manifest.read_text(encoding='utf-8'))['files']:
        if item['name'] in failed:entries[item['name']]=item
results=[]
with httpx.Client(timeout=60,trust_env=False,follow_redirects=True) as client:
    for name,item in entries.items():
        try:
            first=client.get(item['url']);first.raise_for_status()
            if len(first.content)>65536:raise ValueError('Unexpected metadata size')
            ET.fromstring(first.content)
            second=client.get(item['url']);second.raise_for_status()
            if first.content!=second.content:raise ValueError('Provider responses differ')
            target=root/'files'/name
            target.write_bytes(first.content)
            receipt=dict(name=name,state='size_and_sha_recorded',bytes=len(first.content),manifestBytes=int(item['bytes']),
                sha256=hashlib.sha256(first.content).hexdigest(),at=time.time(),sizeException='valid_xml_identical_provider_responses')
            target.with_suffix('.xml.receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
            results.append(receipt)
        except Exception as error:results.append(dict(name=name,state='not_recovered',errorType=type(error).__name__))
(root/'xml-metadata-recovery.json').write_text(json.dumps(dict(at=time.time(),results=results),indent=2),encoding='utf-8')
print(json.dumps(dict(checked=len(results),recovered=sum(r['state']=='size_and_sha_recorded' for r in results))))
