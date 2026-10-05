import {test,expect,type Page} from '@playwright/test';

const polygon={type:'Polygon',coordinates:[[[127,37],[127.001,37],[127.001,37.001],[127,37.001],[127,37]]]};
const binding={project_id:'native-project',owner_project_id:'native-design',branch_id:'main',scene_id:'scene',scene_revision:5,scene_project_id:null};
const panel=(page:Page)=>page.getByRole('region',{name:'신규 설계 명세',exact:true});

async function setup(page:Page,options:{failFirst?:boolean;count?:number;unavailable?:boolean}={}){
  const writes:Array<{request_id:string;scene_revision:number;payload:any}>=[];
  const makeJob=(i:number)=>({job_id:`native-${i}`,project_id:binding.project_id,request_id:`request-${i}`,status:'created',execution_supported:false,
    created_at:'2026-10-04T00:00:00Z',site_area_m2:9876.5,algorithm:'grid',building_type:'업무시설',max_generations:50,population_size:30,
    input_sha256:'a'.repeat(64),scene_revision:5,scene_id:'scene',input:{site_polygon:polygon,job_spec:{options:{building_type:'업무시설',algorithm:'grid'}}},prepared:{options:{algorithm:'grid'}}});
  const jobs=Array.from({length:options.count||0},(_,i)=>makeJob(i));
  await page.route('**/api/v1/platform/projects/native-project',r=>r.fulfill({json:binding}));
  await page.route('**/api/v1/platform/projects/native-project/context',r=>r.fulfill({json:{scene_revision:5,source_versions:{}}}));
  await page.route('**/api/v1/platform/projects/native-project/runs',r=>r.fulfill({json:[]}));
  await page.route('**/api/v1/platform/projects/native-project/design/**',r=>{
    const url=new URL(r.request().url());const path=url.pathname.split('/design')[1];
    if(path==='/selection')return r.fulfill({json:null});
    if(path==='/jobs'||path==='/executions')return r.fulfill({json:{items:[]}});
    if(path==='/native-jobs'&&r.request().method()==='POST'){
      const body=r.request().postDataJSON();writes.push(body);
      if(options.failFirst&&writes.length===1)return r.fulfill({status:503,json:{detail:'storage_unavailable'}});
      const existing=jobs.find(job=>job.request_id===body.request_id);
      if(existing)return r.fulfill({status:201,json:existing});
      const created={...makeJob(jobs.length),request_id:body.request_id,input:body.payload,prepared:body.payload.job_spec};jobs.unshift(created);
      return r.fulfill({status:201,json:created});
    }
    if(path==='/native-jobs'){
      if(options.unavailable)return r.fulfill({status:503,json:{detail:'unavailable'}});
      const offset=Number(url.searchParams.get('offset'));return r.fulfill({json:{items:jobs.slice(offset,offset+20),limit:20,offset}});
    }
    const job=jobs.find(job=>path===`/native-jobs/${job.job_id}`);
    return job?r.fulfill({json:job}):r.fulfill({status:404,json:{detail:'unexpected'}});
  });
  return writes;
}

async function fill(page:Page){
  await panel(page).getByLabel('대지 경계 GeoJSON (WGS84 Polygon)').fill(JSON.stringify(polygon));
  await panel(page).getByRole('combobox',{name:'건물 용도',exact:true}).selectOption('업무시설');
  await panel(page).getByRole('combobox',{name:'매스 생성 방식',exact:true}).selectOption('grid');
}

test('native specification requires a parcel and explicit options, saves original input and reopens without execution',async({page})=>{
  const writes=await setup(page);await page.goto('/projects/native-project');
  await expect(panel(page).getByText('명세 저장 · additive 계산 지원',{exact:true}).first()).toBeVisible();
  await expect(panel(page).getByLabel('대지 경계 GeoJSON (WGS84 Polygon)')).toHaveValue('');
  await fill(page);
  await panel(page).getByLabel('PNU (선택)').fill('1168011200101280003');
  await panel(page).getByLabel('주소 (선택)').fill('사용자 확인 대지');
  await panel(page).getByText('고급 입력',{exact:true}).click();
  const constraints=[{name:'height',type:'Constraint',Requirement:'Less than',val:21,unit:'m',label:'사용자 높이 제한'}];
  await panel(page).getByLabel('제약 조건 JSON 배열 (선택)').fill(JSON.stringify(constraints));
  await panel(page).getByLabel('설계 명세 JSON 객체 (선택)').fill(JSON.stringify({options:{'Number of generations':12,pop_per_island:20,num_islands:2}}));
  await panel(page).getByRole('button',{name:'설계 명세 저장',exact:true}).click();
  await expect(panel(page).getByRole('heading',{name:'저장된 명세 상세',exact:true})).toBeVisible();
  expect(writes).toHaveLength(1);expect(writes[0].scene_revision).toBe(5);
  expect(writes[0].payload).toEqual({site_polygon:polygon,pnu:'1168011200101280003',address:'사용자 확인 대지',constraints,
    job_spec:{options:{'Number of generations':12,pop_per_island:20,num_islands:2,building_type:'업무시설',algorithm:'grid'}}});
  await expect(panel(page).getByRole('img')).toBeVisible();
  await expect(panel(page).getByRole('button',{name:/실행 시작|Run|Generate/})).toHaveCount(0);
  await page.reload();
  await expect(panel(page).getByRole('button',{name:'명세 보기 · native-0',exact:true})).toBeVisible();
  await panel(page).getByRole('button',{name:'명세 보기 · native-0',exact:true}).click();
  await expect(panel(page).locator('.native-design-detail')).toContainText('사용자 높이 제한');expect(writes).toHaveLength(1);
});

test('native failed save preserves fields and request identity while changed input gets a new identity',async({page})=>{
  const writes=await setup(page,{failFirst:true});await page.goto('/projects/native-project');await fill(page);
  await panel(page).getByRole('button',{name:'설계 명세 저장',exact:true}).click();
  await expect(panel(page).getByRole('alert')).toContainText('503');
  await expect(panel(page).getByLabel('대지 경계 GeoJSON (WGS84 Polygon)')).toHaveValue(JSON.stringify(polygon));
  await panel(page).getByRole('button',{name:'설계 명세 저장',exact:true}).click();
  await expect(panel(page).getByRole('heading',{name:'저장된 명세 상세',exact:true})).toBeVisible();
  expect(writes[1]).toEqual(writes[0]);
  await panel(page).getByLabel('주소 (선택)').fill('변경된 주소');
  await panel(page).getByRole('button',{name:'설계 명세 저장',exact:true}).click();
  await expect.poll(()=>writes.length).toBe(3);expect(writes[2].request_id).not.toBe(writes[1].request_id);
});

test('native job pages restore older specifications and errors never masquerade as empty history',async({page})=>{
  await setup(page,{count:25});await page.goto('/projects/native-project');
  await panel(page).getByRole('button',{name:'다음 명세',exact:true}).click();
  await panel(page).getByRole('button',{name:'명세 보기 · native-24',exact:true}).click();
  await expect(panel(page).locator('.native-design-detail')).toContainText('native-24');
  await page.reload();await panel(page).getByRole('button',{name:'다음 명세',exact:true}).click();
  await expect(panel(page).getByRole('button',{name:'명세 보기 · native-24',exact:true})).toBeVisible();
  await page.route('**/design/native-jobs?*',r=>r.fulfill({status:503,json:{detail:'unavailable'}}));
  await page.reload();await expect(panel(page).getByRole('alert')).toContainText('503');
  await expect(panel(page).getByText('저장된 신규 설계 명세가 없습니다.',{exact:true})).toHaveCount(0);
});

test('invalid parcel coordinates and conflicting advanced options never submit',async({page})=>{
  const writes=await setup(page);await page.goto('/projects/native-project');await fill(page);
  await panel(page).getByLabel('대지 경계 GeoJSON (WGS84 Polygon)').fill(JSON.stringify({type:'Polygon',coordinates:[[[300000,400000],[300010,400000],[300010,400010],[300000,400000]]]}));
  await panel(page).getByRole('button',{name:'설계 명세 저장',exact:true}).click();
  await expect(panel(page).getByRole('alert')).toContainText('WGS84');expect(writes).toHaveLength(0);
  await fill(page);await panel(page).getByText('고급 입력',{exact:true}).click();
  await panel(page).getByLabel('설계 명세 JSON 객체 (선택)').fill('{"options":{"algorithm":"additive"}}');
  await panel(page).getByRole('button',{name:'설계 명세 저장',exact:true}).click();
  await expect(panel(page).getByRole('alert')).toContainText('일치');expect(writes).toHaveLength(0);
});

test('unsupported server options are explained and preserve the original form',async({page})=>{
  await setup(page);await page.goto('/projects/native-project');await fill(page);
  await panel(page).getByText('고급 입력',{exact:true}).click();
  const invalid='{"options":{"unsupported_probe":1}}';
  await panel(page).getByLabel('설계 명세 JSON 객체 (선택)').fill(invalid);
  await page.route('**/design/native-jobs',r=>r.fulfill({status:422,json:{detail:{code:'unsupported_fields',message:'Unsupported options fields'}}}));
  await panel(page).getByRole('button',{name:'설계 명세 저장',exact:true}).click();
  await expect(panel(page).getByRole('alert')).toContainText('unsupported_fields');
  await expect(panel(page).getByRole('alert')).toContainText('Unsupported options fields');
  await expect(panel(page).getByLabel('설계 명세 JSON 객체 (선택)')).toHaveValue(invalid);
});

test('actual native specification stores a synthetic parcel and reopens without starting a worker',async({page,request})=>{
  test.skip(!process.env.EDITOR_NATIVE_DESIGN||!process.env.EDITOR_NATIVE_PROJECT,'Requires isolated native design storage fixture');
  const projectId=process.env.EDITOR_NATIVE_PROJECT!;
  const mutations:string[]=[];page.on('request',r=>{if(r.method()==='POST')mutations.push(new URL(r.url()).pathname);});
  await page.goto(`/projects/${encodeURIComponent(projectId)}`);await fill(page);
  await panel(page).getByLabel('주소 (선택)').fill('합성 대지: 명세 저장 검증용 (지적 자료 아님)');
  await panel(page).getByText('고급 입력',{exact:true}).click();
  const options={'Number of generations':12,pop_per_island:20,num_islands:2};
  await panel(page).getByLabel('설계 명세 JSON 객체 (선택)').fill(JSON.stringify({options}));
  const creating=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/design/native-jobs'));
  await panel(page).getByRole('button',{name:'설계 명세 저장',exact:true}).click();
  const created=await creating;expect(created.status()).toBe(201);const job=await created.json();
  expect(job.input.site_polygon).toEqual(polygon);expect(job.status).toBe('created');expect(job.execution_supported).toBe(false);
  expect(job.prepared.job_spec.options).toMatchObject({...options,building_type:'업무시설',algorithm:'grid'});
  await page.reload();
  await panel(page).getByRole('button',{name:`명세 보기 · ${job.job_id}`,exact:true}).click();
  await expect(panel(page).locator('.native-design-detail')).toContainText('명세 저장');
  await expect(panel(page).getByRole('img')).toBeVisible();
  const reopened=await request.get(`/api/v1/platform/projects/${projectId}/design/native-jobs/${job.job_id}`);
  expect(reopened.ok()).toBeTruthy();expect(await reopened.json()).toEqual(job);
  expect(mutations).toEqual([`/api/v1/platform/projects/${projectId}/design/native-jobs`]);
  await panel(page).getByRole('heading',{name:'저장된 명세 상세',exact:true}).scrollIntoViewIfNeeded();
  await page.screenshot({path:'test-results/native-design-actual.png'});
  await test.info().attach('native-job.json',{body:JSON.stringify(job),contentType:'application/json'});
});
