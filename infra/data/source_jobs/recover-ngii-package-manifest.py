import source_job_paths as sjp
import json,re
from pathlib import Path
import httpx
from bs4 import BeautifulSoup

root=Path(str(sjp.NGII_ORIGINAL_ROOT))
prefix=sjp.required_env('NGII_ORDER_PREFIX')
suffixes=json.loads(sjp.required_env('NGII_ORDER_SUFFIXES_JSON'))
with httpx.Client(timeout=60,follow_redirects=True,trust_env=False) as client:
 response=client.post('https://map.ngii.go.kr/pd/purchs/download.do',data={'unityOrderNo':sjp.required_env('NGII_ORDER_NUMBER'),'prcCode':'','orderList':[prefix+s for s in suffixes]})
 response.raise_for_status()
 soup=BeautifulSoup(response.text,'html.parser')
 forms=[{'action':f.get('action'),'fields':[i.get('name') for i in f.select('input')]} for f in soup.select('form')]
 print(json.dumps({'status':response.status_code,'bytes':len(response.content),'forms':forms,'title':soup.title.text if soup.title else None}))
 (root/'package-response.html').write_text(response.text,encoding='utf-8')
