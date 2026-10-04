import {test, expect, type Page} from '@playwright/test';

const binding = {project_id:'binding',owner_project_id:'design-project',branch_id:'main',scene_id:'scene',scene_revision:3,scene_project_id:null};
const job = {source_id:'archive-one',job_id:'job-one',source_status:'running',execution_state:'archived',result_count:2,created_at:'2026-01-01'};
const geometry = {type:'FeatureCollection',crs:{type:'name',properties:{name:'EPSG:4326'}},features:[{type:'Feature',properties:{},
  geometry:{type:'Polygon',coordinates:[[[127,37],[127.001,37],[127.001,37.001],[127,37.001],[127,37]],
    [[127.0002,37.0002],[127.0003,37.0002],[127.0003,37.0003],[127.0002,37.0002]]]}}]};
const candidates = [11,12].map(result_pk=>({...job,result_pk,design_id:7,generation:result_pk,has_mass:true,
  outputs:{gross_floor_area:320+result_pk},is_feasible:true,is_pareto_optimal:true,ranking:1,
  data:{inputs:{width:20},outputs:{gross_floor_area:320+result_pk},mass_geojson:geometry}}));
const mass = {project_id:'design-project',floors:2,footprint_polygon:[[-10,-5],[10,-5],[10,5],[-10,5]],
  floor_footprints:[{floor_index:1,footprint_polygon:[[-10,-5],[10,-5],[10,5],[-10,5]]},
    {floor_index:2,footprint_polygon:[[-8,-4],[8,-4],[8,4],[-8,4]]}],site_edges:[],access_candidates:[],use_mix:{},
  building_code_context:{floor_to_floor_height_m:3},source_provenance:{source:{source_id:'archive-one',job_id:'job-one',result_pk:12,row_sha256:'a'.repeat(64)},
    mass_sha256:'b'.repeat(64),source_crs:'EPSG:4326',projected_crs:'EPSG:32652',units:'m',origin_projected:[320000,4100000],
    origin_wgs84:[127,37],height_m:6,building_type:'office',representation:'simple'}};

async function mockProject(page: Page, options: {conflict?:boolean;unavailable?:boolean;delayFirst?:Promise<void>} = {}) {
  let attached=false;
  let selection:typeof candidates[number]|null=null;
  await page.route('**/api/v1/platform/projects/binding',r=>r.fulfill({json:binding}));
  await page.route('**/api/v1/platform/projects/binding/context',r=>r.fulfill({json:{scene_revision:3,source_versions:{}}}));
  await page.route('**/api/v1/platform/projects/binding/runs',r=>r.fulfill({json:[]}));
  await page.route('**/api/v1/platform/projects/binding/design/**',async r=>{
    const url=new URL(r.request().url());const path=url.pathname.split('/design')[1];const post=r.request().method()==='POST';
    if(path==='/executions')return r.fulfill({json:{items:[]}});
    if(options.unavailable)return r.fulfill({status:503,json:{detail:'unavailable'}});
    if(path==='/jobs'&&post){
      expect(r.request().postDataJSON()).toEqual({source_id:job.source_id,job_id:job.job_id,scene_revision:3});
      attached=true;return r.fulfill({status:201,json:job});
    }
    if(path==='/jobs')return r.fulfill({json:{items:attached?[job]:[]}});
    if(path==='/archive/jobs'){
      const offset=Number(url.searchParams.get('offset'));
      return r.fulfill({json:{items:offset===0?[job,...Array.from({length:19},(_,i)=>({...job,job_id:`other-${i}`}))]:[],limit:20,offset}});
    }
    if(path==='/selection'&&post){
      const body=r.request().postDataJSON();expect(body.scene_revision).toBe(3);
      if(options.conflict)return r.fulfill({status:409,json:{detail:'stale_scene_revision'}});
      selection=candidates.find(item=>item.result_pk===body.result_pk)!;
      return r.fulfill({json:selection});
    }
    if(path==='/selection')return r.fulfill({json:selection});
    if(path==='/jobs/archive-one/job-one')return r.fulfill({json:{...job,data:{constraints:{max_height:12},job_spec:{floors:2},site_polygon:geometry}}});
    if(path.endsWith('/results'))return r.fulfill({json:{items:candidates,limit:20,offset:0}});
    const candidate=candidates.find(item=>path.endsWith(`/results/${item.result_pk}`));
    if(candidate){
      if(candidate.result_pk===11&&options.delayFirst)await options.delayFirst;
      return r.fulfill({json:candidate}).catch(()=>{});
    }
    return r.fulfill({status:404,json:{detail:'unexpected test request'}});
  });
}

async function attachFirstJob(page: Page) {
  await page.goto('/projects/binding');
  await page.getByRole('button',{name:'보관된 작업 찾아보기',exact:true}).click();
  await expect(page.getByText('보관됨 · 원본 상태: running · 후보 2개 · 저장 시각: 2026-01-01',{exact:true}).first()).toBeVisible();
  await page.getByRole('button',{name:'프로젝트에 연결 · job-one',exact:true}).click();
  await expect(page.getByRole('button',{name:'후보 상세 · 원본 PK 12',exact:true})).toBeVisible();
}

test('archived candidates retain original PK, geometry and selection across reload',async({page})=>{
  await mockProject(page);await attachFirstJob(page);
  await page.getByRole('button',{name:'다음 작업',exact:true}).click();
  await expect(page.getByText('이 범위에 보관된 작업이 없습니다.',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'이전 작업',exact:true}).click();
  await expect(page.getByRole('button',{name:'연결됨 · job-one',exact:true})).toBeDisabled();
  await page.getByRole('button',{name:'후보 상세 · 원본 PK 12',exact:true}).click();
  await expect(page.getByRole('heading',{name:'설계 후보 상세 · 원본 PK 12',exact:true})).toBeVisible();
  const preview=page.getByRole('img',{name:'저장된 설계 평면 형상'});
  await expect(preview.locator('path')).toHaveAttribute('fill-rule','evenodd');
  expect((await preview.locator('path').getAttribute('d'))?.match(/M/g)).toHaveLength(2);
  await expect(page.locator('.saved-design-footprint').getByText('EPSG:4326',{exact:false})).toBeVisible();
  await expect(page.getByText('"max_height": 12',{exact:false})).toBeVisible();
  await expect(page.getByText('"gross_floor_area": 332',{exact:false})).toBeVisible();
  await page.getByRole('button',{name:'프로젝트 설계로 선택',exact:true}).click();
  await expect(page.getByTestId('saved-design-selection')).toContainText('원본 PK 12');
  await page.reload();
  await expect(page.getByTestId('saved-design-selection')).toContainText('원본 PK 12');
  await expect(page.getByRole('heading',{name:'설계 후보 상세 · 원본 PK 12',exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:'이 후보가 저장되어 있습니다',exact:true})).toBeDisabled();
  await expect(page.getByRole('link',{name:'선택한 설계로 평면 계획 검토'})).toHaveAttribute('href','/planm?designProject=binding');
  await page.screenshot({path:'test-results/saved-design-reopened.png',fullPage:true});
  await page.locator('.design-detail').screenshot({path:'test-results/saved-design-detail.png'});
});

test('stale scene selection remains unsaved and unavailable archive remains an error',async({page})=>{
  await mockProject(page,{conflict:true});await attachFirstJob(page);
  await page.getByRole('button',{name:'후보 상세 · 원본 PK 11',exact:true}).click();
  await page.getByRole('button',{name:'프로젝트 설계로 선택',exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('409');
  await expect(page.getByTestId('saved-design-selection')).toHaveCount(0);
  await page.unroute('**/api/v1/platform/projects/binding/design/**');
  await page.route('**/api/v1/platform/projects/binding/design/**',r=>new URL(r.request().url()).pathname.endsWith('/executions')
    ?r.fulfill({json:{items:[]}}):r.fulfill({status:503,json:{detail:'unavailable'}}));
  await page.reload();
  await expect(page.getByRole('alert')).toContainText('503');
  await expect(page.getByText('연결된 설계 작업이 없습니다.',{exact:true})).toHaveCount(0);
});

test('delayed detail never replaces a newer candidate',async({page})=>{
  let release!:()=>void;const gate=new Promise<void>(resolve=>{release=resolve;});
  await mockProject(page,{delayFirst:gate});await attachFirstJob(page);
  const first=page.waitForRequest('**/results/11');
  await page.getByRole('button',{name:'후보 상세 · 원본 PK 11',exact:true}).click();await first;
  await page.getByRole('button',{name:'후보 상세 · 원본 PK 12',exact:true}).click();
  await expect(page.getByRole('heading',{name:'설계 후보 상세 · 원본 PK 12',exact:true})).toBeVisible();
  release();
  await expect(page.getByRole('heading',{name:'설계 후보 상세 · 원본 PK 11',exact:true})).toHaveCount(0);
});

test('selected mass preview requires explicit start and preserves the exact PLANM payload',async({page})=>{
  let posts=0;
  await page.route('**/design/selection/mass',r=>r.fulfill({json:{mass}}));
  await page.route('**/api/v1/planm/runs',r=>{
    posts++;expect(r.request().postDataJSON()).toEqual({contract_version:'planm-run-create/v1',mass:{...mass,use_mix:{office:1}}});
    return r.fulfill({json:{contract_version:'planm-run/v1',run_id:'saved-mass-run',project_id:'design-project',status:'blocked',stage:'normalize',approved_alternative_id:null,violations:[]}});
  });
  await page.route('**/api/v1/planm/runs/saved-mass-run/alternatives',r=>r.fulfill({status:404,json:{detail:'none'}}));
  await page.goto('/planm?designProject=binding');
  await expect(page.getByRole('heading',{name:'선택한 설계로 평면 계획',exact:true})).toBeVisible();
  await expect(page.getByText('저장된 층수: 2 · 높이: 6 m · 건물 유형: office',{exact:true})).toBeVisible();
  await expect(page.getByRole('img',{name:'저장된 설계 평면 형상'})).toBeVisible();
  await expect(page.getByLabel('Project ID',{exact:true})).toHaveCount(0);expect(posts).toBe(0);
  await expect(page.getByLabel('계획 검토 용도')).toHaveValue('');
  await expect(page.getByRole('button',{name:'선택한 형상으로 평면 계획 시작',exact:true})).toBeDisabled();
  await expect(page.getByLabel('계획 검토 용도').locator('option[value="neighborhood_commercial"]')).toHaveJSProperty('disabled',true);
  await page.getByLabel('계획 검토 용도').selectOption('office');
  await page.getByRole('button',{name:'선택한 형상으로 평면 계획 시작',exact:true}).click();
  await expect(page.getByRole('heading',{name:'design-project',exact:true})).toBeVisible();expect(posts).toBe(1);
});

test('unsupported saved mass cannot start a guessed alternative',async({page})=>{
  let posts=0;
  await page.route('**/design/selection/mass',r=>r.fulfill({status:422,json:{detail:{code:'unsupported_mass_representation'}}}));
  await page.route('**/api/v1/planm/runs',r=>{posts++;return r.abort();});
  await page.goto('/planm?designProject=binding');
  await expect(page.getByRole('alert')).toContainText('변환할 수 없습니다');
  await expect(page.getByRole('button',{name:'선택한 형상으로 평면 계획 시작',exact:true})).toBeDisabled();
  expect(posts).toBe(0);
});

test('a delayed previous run poll cannot replace the newly started saved-mass run',async({page})=>{
  let posts=0;let release!:()=>void;let completed!:()=>void;
  const gate=new Promise<void>(resolve=>{release=resolve;});
  const done=new Promise<void>(resolve=>{completed=resolve;});
  const run=(id:string,status:string)=>({contract_version:'planm-run/v1',run_id:id,project_id:id,
    status,stage:'normalize',approved_alternative_id:null,violations:[]});
  await page.route('**/design/selection/mass',r=>r.fulfill({json:{mass}}));
  await page.route('**/api/v1/planm/runs',r=>r.fulfill({json:++posts===1?run('old-run','queued'):run('new-run','blocked')}));
  await page.route('**/api/v1/planm/runs/new-run/alternatives',r=>r.fulfill({status:404,json:{detail:'none'}}));
  await page.route('**/api/v1/planm/runs/old-run',async r=>{
    await gate;await r.fulfill({json:run('old-run','running')});completed();
  });
  await page.goto('/planm?designProject=binding');
  const poll=page.waitForRequest('**/api/v1/planm/runs/old-run');
  await page.getByLabel('계획 검토 용도').selectOption('office');
  await page.getByRole('button',{name:'선택한 형상으로 평면 계획 시작',exact:true}).click();await poll;
  await page.getByRole('button',{name:'선택한 형상으로 평면 계획 시작',exact:true}).click();
  await expect(page.getByRole('heading',{name:'new-run',exact:true})).toBeVisible();
  const response=page.waitForResponse('**/api/v1/planm/runs/old-run');release();await done;
  await (await response).finished();
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  await expect(page.getByRole('heading',{name:'new-run',exact:true})).toBeVisible();
  await expect(page.getByRole('heading',{name:'old-run',exact:true})).toHaveCount(0);
});

test('non-text archived building type does not crash the saved-mass preview',async({page})=>{
  await page.route('**/design/selection/mass',r=>r.fulfill({json:{mass:{...mass,
    source_provenance:{...mass.source_provenance,building_type:{archived:'office'}}}}}));
  await page.goto('/planm?designProject=binding');
  await expect(page.getByText('저장된 층수: 2 · 높이: 6 m · 건물 유형: 미확인',{exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:'선택한 형상으로 평면 계획 시작',exact:true})).toBeDisabled();
  await page.getByLabel('계획 검토 용도').selectOption('office');
  await expect(page.getByRole('button',{name:'선택한 형상으로 평면 계획 시작',exact:true})).toBeEnabled();
});

test('isolated imported design attaches, restores selection and previews the actual saved mass',async({page,request})=>{
  test.skip(!process.env.EDITOR_SAVED_DESIGN || !process.env.EDITOR_DESIGN_PROJECT,'Requires isolated imported design history and a scene binding');
  const projectId=process.env.EDITOR_DESIGN_PROJECT!;
  const prefix=`/api/v1/platform/projects/${encodeURIComponent(projectId)}/design`;
  const archive=await request.get(`${prefix}/archive/jobs?limit=20&offset=0`);
  expect(archive.ok()).toBeTruthy();const first=(await archive.json()).items[0];
  expect(first.execution_state).toBe('archived');
  await page.goto(`/projects/${encodeURIComponent(projectId)}`);
  await page.getByRole('button',{name:'보관된 작업 찾아보기',exact:true}).click();
  await expect(page.getByRole('button',{name:new RegExp(`^(프로젝트에 연결|연결됨) · ${first.job_id}$`)})).toBeVisible();
  const attach=page.getByRole('button',{name:`프로젝트에 연결 · ${first.job_id}`,exact:true});
  if(await attach.count())await attach.click();
  else await expect(page.getByRole('button',{name:`연결됨 · ${first.job_id}`,exact:true})).toBeDisabled();
  await page.getByRole('button',{name:`후보 보기 · ${first.job_id}`,exact:true}).click();
  const response=await request.get(`${prefix}/jobs/${encodeURIComponent(first.source_id)}/${first.job_id}/results?limit=20&offset=0`);
  expect(response.ok()).toBeTruthy();const candidate=(await response.json()).items[0];
  await page.getByRole('button',{name:`후보 상세 · 원본 PK ${candidate.result_pk}`,exact:true}).click();
  await expect(page.getByRole('heading',{name:`설계 후보 상세 · 원본 PK ${candidate.result_pk}`,exact:true})).toBeVisible();
  await expect(page.getByRole('img',{name:'저장된 설계 평면 형상'})).toBeVisible();
  const select=page.getByRole('button',{name:'프로젝트 설계로 선택',exact:true});
  if(await select.count())await select.click();
  await expect(page.getByTestId('saved-design-selection')).toContainText(`원본 PK ${candidate.result_pk}`);
  await page.reload();
  await expect(page.getByRole('heading',{name:`설계 후보 상세 · 원본 PK ${candidate.result_pk}`,exact:true})).toBeVisible();
  const selected=await request.get(`${prefix}/selection`);expect(selected.ok()).toBeTruthy();
  const selection=await selected.json();expect(selection.result_pk).toBe(candidate.result_pk);
  expect(selection.source_id).toBe(first.source_id);expect(selection.data.mass_geojson).toBeTruthy();
  await page.locator('.design-detail').screenshot({path:'test-results/saved-design-actual-detail.png'});
  let runs=0;page.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith('/api/v1/planm/runs'))runs++;});
  const bridge=page.waitForResponse(r=>r.url().endsWith('/design/selection/mass'));
  await page.getByRole('link',{name:'선택한 설계로 평면 계획 검토',exact:true}).click();
  const converted=await bridge;expect(converted.ok()).toBeTruthy();const payload=await converted.json();
  expect(payload.mass.source_provenance.source.result_pk).toBe(candidate.result_pk);
  await expect(page.getByRole('button',{name:'선택한 형상으로 평면 계획 시작',exact:true})).toBeDisabled();
  await page.getByLabel('계획 검토 용도').selectOption('office');
  await expect(page.getByRole('button',{name:'선택한 형상으로 평면 계획 시작',exact:true})).toBeEnabled();
  await expect(page.getByRole('img',{name:'저장된 설계 평면 형상'})).toBeVisible();
  expect(runs).toBe(0);
  await page.locator('.saved-mass-brief').screenshot({path:'test-results/saved-design-actual-mass.png'});
});
