import source_job_paths as sjp
import hashlib,json,shutil,time
from pathlib import Path
from urllib.parse import urlencode
import httpx

root=Path(str(sjp.NGII_ORIGINAL_ROOT));root.mkdir(parents=True,exist_ok=True)
name='(B010)수치지도_37608004_2025_00000137993578.dxf'
expected=6493321
directory=sjp.required_env('NGII_PROBE_DIRECTORY')
url='https://nlippd.ngii.go.kr/nlippd/pd/innorix/innorixDownLoad2.do?'+urlencode({'fileName':name,'directory':directory})
target=root/name;part=target.with_suffix('.dxf.part')
assert shutil.disk_usage(root).free>expected+20_000_000_000,'storage reserve'
with httpx.Client(timeout=60,follow_redirects=True,trust_env=False) as client:
 with client.stream('GET',url) as response:
  response.raise_for_status()
  assert 'text/html' not in response.headers.get('content-type',''),'HTML instead of original'
  size=0;digest=hashlib.sha256()
  with part.open('wb') as stream:
   for block in response.iter_bytes(1024*1024):
    size+=len(block)
    assert size<=expected,'oversized response'
    stream.write(block);digest.update(block)
assert size==expected,f'size mismatch {size}/{expected}'
part.replace(target)
receipt={'at':time.time(),'name':name,'bytes':size,'sha256':digest.hexdigest(),'path':str(target),'state':'downloaded_size_verified','region':'41480','source':'NGII authorized package download','geometryValidated':False}
(root/'probe-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(receipt,ensure_ascii=True))
