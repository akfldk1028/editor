import source_job_paths as sjp
import concurrent.futures, json, time
from pathlib import Path
import httpx
cities=[('Gosan',37.7294,127.1084),('Seoul',37.5665,126.978),('Incheon',37.4563,126.7052),('Suwon',37.2636,127.0286),('Chuncheon',37.8813,127.73),('Gangneung',37.7519,128.8761),('Cheongju',36.6424,127.489),('Daejeon',36.3504,127.3845),('Sejong',36.4801,127.289),('Hongseong',36.6012,126.6608),('Jeonju',35.8242,127.148),('Gwangju',35.1595,126.8526),('Mokpo',34.8118,126.3922),('Daegu',35.8714,128.6014),('Andong',36.5684,128.7294),('Busan',35.1796,129.0756),('Ulsan',35.5384,129.3114),('Changwon',35.2285,128.6811),('Jeju',33.4996,126.5312),('Ulleung',37.4844,130.9057),('Dokdo',37.2411,131.8652)]
def probe(city):
 name,lat,lon=city
 row={'city':name,'lat':lat,'lon':lon}
 with httpx.Client(base_url='http://127.0.0.1:18449',trust_env=False,timeout=60) as c:
  for kind,path,params in [('terrain','terrain-heights',dict(west=lon-.001,south=lat-.001,east=lon+.001,north=lat+.001,size=3)),('roads','context-ground',dict(lat=lat,lon=lon,radius_m=320,detail='roads'))]:
   start=time.perf_counter()
   try:
    r=c.get('/api/v1/land/'+path,params=params); data=r.json()
    row[kind]={'status':r.status_code,'seconds':round(time.perf_counter()-start,3)}
    if kind=='terrain': row[kind].update(heights=data.get('heights'),detail=data.get('detail'))
    else:
     row[kind]['response']=data
     row[kind]['data_status']=data.get('status')
     row[kind]['has_features']=bool(data.get('features'))
   except Exception as e: row[kind]={'error':str(e)}
 print(name,row['terrain']['status'] if 'status' in row['terrain'] else row['terrain'],row['roads'].get('status'),row['roads'].get('data_status'),flush=True)
 return row
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(probe,cities))
p=Path(str(sjp.INDEX_STATE_ROOT / 'national-service-probes-20261023.json'))
p.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
print('saved',p)
