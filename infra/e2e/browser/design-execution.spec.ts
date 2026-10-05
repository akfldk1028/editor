import {test,expect} from '@playwright/test';

test('execution retry retains request identity and a failed history read never enables launch',async({page})=>{
  const jobId='a'.repeat(32),attemptId='b'.repeat(32),writes:any[]=[],attempts:any[]=[];
  const job={job_id:jobId,project_id:'execution-mock',request_id:'spec',status:'created',execution_supported:false,
    created_at:'2026-10-05T00:00:00Z',site_area_m2:1000,algorithm:'additive',building_type:'업무시설',
    max_generations:2,population_size:16,input_sha256:'c'.repeat(64),scene_revision:2,scene_id:'scene',
    input:{site_polygon:{type:'Polygon',coordinates:[[[127,37],[127.001,37],[127.001,37.001],[127,37.001],[127,37]]]}},prepared:{}};
  await page.route('**/api/v1/platform/projects/execution-mock**',r=>{
    const path=new URL(r.request().url()).pathname.split('execution-mock')[1];
    if(path==='')return r.fulfill({json:{project_id:'execution-mock',owner_project_id:'owner',branch_id:'main',scene_id:'scene',scene_revision:2,scene_project_id:null}});
    if(path==='/runs')return r.fulfill({json:[]});
    if(path==='/design/native-jobs')return r.fulfill({json:{items:[job]}});
    if(path===`/design/native-jobs/${jobId}`)return r.fulfill({json:job});
    if(path.endsWith('/attempts')) {
      if(r.request().method()==='GET')return r.fulfill({json:{items:attempts}});
      const body=r.request().postDataJSON();writes.push(body);
      if(writes.length===1)return r.fulfill({status:503,json:{detail:'unavailable'}});
      const attempt={attempt_id:attemptId,project_id:'execution-mock',job_id:jobId,request_id:body.request_id,seed:String(body.seed),scene_revision:2,status:'queued',created_at:'2026-10-05'};
      attempts.push(attempt);return r.fulfill({status:202,json:attempt});
    }
    if(path.endsWith('/events'))return r.fulfill({json:{items:[{sequence:1,type:'queued'}]}});
    if(path==='/design/selection')return r.fulfill({json:null});
    if(path==='/context')return r.fulfill({json:{scene_revision:2,source_versions:{}}});
    return r.fulfill({json:{items:[]}});
  });
  await page.goto('/projects/execution-mock');
  await page.getByRole('button',{name:`명세 보기 · ${jobId}`,exact:true}).click();
  const panel=page.getByRole('region',{name:'매스 계산 실행',exact:true});
  await panel.getByRole('checkbox').check();
  await panel.getByRole('button',{name:'계산 시작',exact:true}).click();
  await expect(panel.getByRole('alert')).toContainText('503');
  await panel.getByRole('button',{name:'계산 시작',exact:true}).click();
  await expect(panel.getByRole('status')).toHaveText('실행 상태: 대기 중');
  expect(writes).toHaveLength(2);expect(writes[0]).toEqual(writes[1]);
  await page.route('**/attempts?*',r=>r.fulfill({status:503,json:{detail:'storage unavailable'}}));
  await panel.getByRole('button',{name:'실행 목록 새로고침',exact:true}).click();
  await expect(panel.getByRole('alert')).toContainText('503');
  await expect(panel.getByRole('button',{name:'계산 시작',exact:true})).toBeDisabled();
  expect(writes).toHaveLength(2);
});

test('actual standalone worker: create, run, reload, cancel and explicitly restart',async({page,request})=>{
  test.skip(!process.env.EDITOR_EXECUTION_UI_PROJECT,'Requires isolated HTTP service and standalone worker');
  test.setTimeout(120000);
  const project=process.env.EDITOR_EXECUTION_UI_PROJECT!;
  const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message));
  await page.goto(`/projects/${project}`);
  const specification=page.getByRole('region',{name:'신규 설계 명세',exact:true});
  const polygon={type:'Polygon',coordinates:[[[127,37.5],[127.001,37.5],[127.001,37.501],[127,37.501],[127,37.5]]]};
  await specification.getByLabel('대지 경계 GeoJSON (WGS84 Polygon)').fill(JSON.stringify(polygon));
  await specification.getByRole('combobox',{name:'건물 용도',exact:true}).selectOption('업무시설');
  await specification.getByRole('combobox',{name:'매스 생성 방식',exact:true}).selectOption('additive');
  await specification.getByLabel('주소 (선택)').fill('합성 대지 · 실행 UI 검증용');
  const created=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/native-jobs'));
  await specification.getByRole('button',{name:'설계 명세 저장',exact:true}).click();
  const job=await (await created).json();
  const panel=page.getByRole('region',{name:'매스 계산 실행',exact:true});
  await expect(panel.getByRole('button',{name:'계산 시작',exact:true})).toBeDisabled();
  await panel.getByRole('checkbox').check();
  await panel.getByRole('button',{name:'계산 시작',exact:true}).click();
  await expect(panel.getByRole('status')).toHaveText('실행 상태: 계산 종료',{timeout:60000});
  await expect(panel.getByRole('img')).toBeVisible();
  await panel.getByText(/실행 기록 \(/).click();
  await expect(panel).toContainText('generation');
  await expect(panel).toContainText('평가 1050개');
  await panel.getByRole('img').scrollIntoViewIfNeeded();
  await page.screenshot({path:'test-results/design-execution-actual.png'});
  const endpoint=`/api/v1/platform/projects/${project}/design/native-jobs/${job.job_id}/attempts`;
  const first=(await (await request.get(endpoint)).json()).items[0];
  const saved=await (await request.get(`${endpoint}/${first.attempt_id}/result`)).json();
  expect(saved.candidates.length).toBeGreaterThan(0);
  await page.reload();
  await specification.getByRole('button',{name:`명세 보기 · ${job.job_id}`,exact:true}).click();
  await expect(panel.getByRole('img')).toBeVisible();
  expect(await (await request.get(`${endpoint}/${first.attempt_id}/result`)).json()).toEqual(saved);
  await panel.getByRole('checkbox').check();
  await panel.getByRole('button',{name:'새 시도로 재실행',exact:true}).click();
  await panel.getByRole('button',{name:'실행 취소',exact:true}).click();
  await expect(panel.getByRole('status')).toHaveText('실행 상태: 취소됨',{timeout:30000});
  await panel.getByRole('button',{name:'새 시도로 재실행',exact:true}).click();
  await expect(panel.getByRole('status')).toHaveText('실행 상태: 계산 종료',{timeout:60000});
  const attempts=(await (await request.get(endpoint)).json()).items;
  expect(attempts.map((item:any)=>item.status)).toEqual(['computed','cancelled','computed']);
  expect(new Set(attempts.map((item:any)=>item.attempt_id)).size).toBe(3);
  expect(errors).toEqual([]);
  await test.info().attach('execution-evidence.json',{body:JSON.stringify({project,job_id:job.job_id,attempts}),contentType:'application/json'});
});
