"""Read-only five-minute tracking of national map preparation and serving."""
import source_job_paths as sjp
import json,msvcrt,os,time
from pathlib import Path
from datetime import datetime
import psutil
import httpx
from national_delivery_probe import probe_building_delivery
ROOT=Path(str(sjp.NGII_DEM_ROOT))
CATALOG=Path(str(sjp.DATA_ROOT / 'world-buildings/catalog.json'))
LATEST=ROOT/'national-tracking.json'
lock=(ROOT/'national-tracking.lock').open('a+b')
if os.fstat(lock.fileno()).st_size==0:lock.write(b'0');lock.flush()
lock.seek(0)
try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
except OSError:raise SystemExit('National tracking already running')
(ROOT/'national-tracking.pid').write_text(str(os.getpid()))
def read(path):
 for attempt in range(4):
  try:return json.loads(path.read_text(encoding='utf-8-sig'))
  except (OSError,ValueError):
   if attempt==3:raise
   time.sleep(.1)
def write(path,data):
 temp=path.with_suffix('.tracking-tmp');temp.write_text(data,encoding='utf-8')
 for attempt in range(5):
  try:temp.replace(path);return
  except PermissionError:
   if attempt==4:raise
   time.sleep(.1)
def alive(pid,script):
 try:return any(script in arg for arg in psutil.Process(int(pid)).cmdline())
 except (psutil.Error,ValueError,TypeError):return False
while True:
 try:
  now=time.time();previous=read(LATEST) if LATEST.exists() else None
  terrain=read(ROOT/'national-progress.json');job=read(ROOT/'national-buildings-status.json')
  catalog=read(CATALOG);regions=catalog['regions']
  count=sum(sum(r['counts'].values()) for r in regions)
  publisher_alive=alive(job.get('pid'),'national-buildings-loop.py')
  log=ROOT/'national-buildings-bake.log'
  log_age=now-log.stat().st_mtime if log.exists() else None
  alerts=[]
  assets=read(ROOT/'national-published-assets-audit.json') if (ROOT/'national-published-assets-audit.json').exists() else {}
  assets_alive=alive(assets.get('pid'),'audit-published-national-buildings.ts')
  if assets.get('invalid'):alerts.append('published_assets_invalid')
  if assets.get('state')=='running' and not assets_alive:alerts.append('published_assets_audit_stopped')
  if assets.get('state')=='catalog_changed_requires_followup':alerts.append('published_catalog_changed_during_audit')
  package_root=Path(str(sjp.NGII_ORIGINAL_ROOT))
  package_status={}
  for name,filename,script in [('orders','batch-order-status.json',None),('downloads','download-status.json','download-ngii-packages.py'),('terrain_staging','terrain-stage-status.json','stage-ngii-dxf-ground.py'),('national_partial_rebake','national-partial-rebake-status.json','rebuild-national-partial-ground.py'),('batch_finish','batch-finish-status.json','finish-ngii-package-batch.py'),('package_buildings','building-rebake-status.json','rebake-ngii-package-regions.py')]:
   path=package_root/filename
   if not path.exists():continue
   status=read(path)
   details=status.pop('results',None)
   if isinstance(details,list):
    status['resultCount']=len(details)
    status['failedResults']=sum(r.get('state')=='failed' or r.get('exitCode',0) not in (0,2) for r in details)
    if status['failedResults']:alerts.append(name+'_failed_results')
   if script:status['process_alive']=alive(status.get('pid'),script)
   if script and status.get('state') in ('running','waiting','waiting_for_publisher') and not status['process_alive']:alerts.append(name+'_process_stopped')
   if status.get('state') in ('failed','finished_with_failures'):alerts.append(name+'_failed')
   package_status[name]=status
  install_path=package_root/'terrain-install-receipt.json'
  if install_path.exists():
   installed=read(install_path)
   package_status['installed_ground']={'at':installed.get('at'),'patches':len(installed.get('installed',[])),'verifiedRecords':len(installed.get('verifiedKeys',[])),'regions':len(installed.get('regions',[]))}
  terminal=job.get('state') in ('building_preparation_complete','failed','needs_evidence','needs_storage')
  if not publisher_alive and not terminal:alerts.append('publisher_process_missing')
  if job.get('state') in ('failed','needs_evidence','needs_storage'):alerts.append(job['state'])
  if publisher_alive and job.get('state')=='running' and log_age is not None and log_age>900:alerts.append('no_log_progress_15min')
  acquisition=read(ROOT/'national-gap-acquisition.json') if (ROOT/'national-gap-acquisition.json').exists() else {}
  coverage=read(ROOT/'national-original-gap-coverage.json') if (ROOT/'national-original-gap-coverage.json').exists() else {}
  coverage={k:v for k,v in coverage.items() if k!='regions'}
  acquisition_alive=alive(acquisition.get('pid'),'acquire-national-ground-gaps.py')
  coverage_alive=alive(coverage.get('pid'),'audit-original-gap-coverage.py')
  if acquisition and acquisition.get('state')!='source_acquisition_finished' and not acquisition_alive:alerts.append('original_source_acquisition_stopped')
  if coverage and coverage.get('regionsAudited',0)<coverage.get('totalRegions',0) and not coverage_alive:alerts.append('original_source_audit_stopped')
  if coverage and coverage.get('regionsAudited')==coverage.get('totalRegions') and coverage.get('supportedByOriginalTIN',0)<coverage.get('missingRecords',0):alerts.append('additional_precise_ground_source_required')
  delivery={}
  try:
   with httpx.Client(base_url='http://127.0.0.1:3003',trust_env=False,timeout=5) as client:
    delivery=probe_building_delivery(client,regions[-1])
   if not delivery['valid_tileset']:alerts.append('latest_tileset_not_served')
  except Exception as error:delivery={'error':str(error)};alerts.append('delivery_probe_failed')
  elapsed=now-previous['at'] if previous else None
  row={'at':now,'local_time':datetime.now().astimezone().isoformat(),'interval_seconds':300,
       'terrain':terrain,'building_state':job.get('state'),'phase':job.get('phase'),
       'publisher_pid':job.get('pid'),'publisher_alive':publisher_alive,
       'regions':len(regions),'building_records':count,
       'since_previous':{'seconds':round(elapsed,1),'regions':len(regions)-previous['regions'],
                        'building_records':count-previous['building_records']} if previous else None,
       'log_age_seconds':round(log_age,1) if log_age is not None else None,
       'free_gb':{drive:round(psutil.disk_usage(drive).free/1e9,2) for drive in sjp.STORAGE_ROOTS},
       'delivery':delivery,'alerts':alerts,'eta':None,
       'published_assets_audit':{**assets,'process_alive':assets_alive},
       'ngii_original_packages':package_status,
       'original_source_acquisition':{**acquisition,'process_alive':acquisition_alive},
       'original_source_coverage':{**coverage,'process_alive':coverage_alive},
       'original_source_repair':read(ROOT/'national-original-patch-delivery.json') if (ROOT/'national-original-patch-delivery.json').exists() else None,
       'gap_audit':read(ROOT/'national-gap-reference-audit.json') if (ROOT/'national-gap-reference-audit.json').exists() else None,
       'reference_height_comparison':read(ROOT/'national-gap-reference-height-comparison.json') if (ROOT/'national-gap-reference-height-comparison.json').exists() else None,
       'eta_reason':'Total remaining building work and missing-ground remediation are not yet quantified'}
  write(LATEST,json.dumps(row,ensure_ascii=False,indent=2))
  with (ROOT/'national-tracking-history.jsonl').open('a',encoding='utf-8') as history:
   history.write(json.dumps(row,ensure_ascii=False)+'\n')
  report=f'''# 전국 지도 처리 추적

갱신: {row['local_time']} · 5분 간격 자동 확인

- 지형: {terrain['completed']}/{terrain['total']} 후보 구역 · {terrain['state']}
- 건물: {len(regions):,}개 지역 타일 · 카탈로그 건물 레코드 {count:,}개
- 건물 작업: {job.get('state')} / {job.get('phase')} · 프로세스 실행 {publisher_alive}
- 직전 기록 대비: {row['since_previous']}
- 최근 작업 로그 경과: {row['log_age_seconds']}초
- 최신 타일 제공 검사: {delivery}
- 확인할 항목: {', '.join(alerts) or '없음'}
- 남은 저장 공간(GB): {row['free_gb']}
- 원본 다운로드·지형 처리·최종 검증: {json.dumps(package_status,ensure_ascii=False)}

전체 건물 수와 누락 지반 자료의 재처리 시간이 확정되지 않아 종료 시각은 아직 산출하지 않습니다.
카탈로그 집계는 중복 제거된 전국 건물 총수나 전체 화면 검증 완료를 뜻하지 않습니다.
이 프로세스는 상태를 기록하며 채팅에 자동 메시지를 보내지는 않습니다.
'''
  write(ROOT/'national-tracking.md',report)
  print(json.dumps({'at':row['local_time'],'regions':len(regions),'building_records':count,'alerts':alerts}),flush=True)
  if job.get('state')=='building_preparation_complete' and terrain.get('state')=='complete' and not alerts:break
 except Exception as error:
  print(json.dumps({'at':time.time(),'tracking_error':str(error)}),flush=True)
 time.sleep(300)
