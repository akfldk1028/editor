import { test, expect } from '@playwright/test';

test.beforeEach(async ({page}) => {
  await page.route('**/api/v1/platform/projects/*/design/jobs',r=>r.fulfill({json:{items:[]}}));
  await page.route('**/api/v1/platform/projects/*/design/selection',r=>r.fulfill({json:null}));
  await page.route('**/api/v1/platform/projects/*/design/executions*',r=>r.fulfill({json:{items:[]}}));
});

test('local zoning catalog populates form with legacy service unconfigured', async ({page, request}) => {
  test.skip(!process.env.EDITOR_LOCAL_ZONES, 'Requires isolated backend without a legacy URL');
  const response = await request.get('/api/v1/land/zones');
  expect(response.status()).toBe(200);
  const catalog = await response.json();
  expect(catalog.count).toBe(21);
  expect((await request.get('/api/v1/land/stats')).status()).toBe(503);
  await page.goto('/land');
  const select = page.getByLabel('용도지역 직접 지정');
  await expect(select.locator('option')).toHaveCount(catalog.count + 1);
  await select.selectOption(catalog.zones[0].zone_name);
  await expect(select).toHaveValue(catalog.zones[0].zone_name);
  await page.reload();
  await expect(select.locator('option')).toHaveCount(catalog.count + 1);
  await page.getByLabel('주소 또는 PNU').fill('11680-11200-10128-0003');
  await page.getByRole('button',{name:'주소/PNU 확인',exact:true}).click();
  await expect(page.getByText('PNU 코드 형식 확인: 1168011200101280003',{exact:true})).toBeVisible();
  await page.getByLabel('주소 또는 PNU').fill('address without configured provider');
  await expect(page.getByText('PNU 코드 형식 확인: 1168011200101280003',{exact:true})).toHaveCount(0);
  await page.getByRole('button',{name:'주소/PNU 확인',exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('not configured');
});

test('live land form runs analysis in Editor', async ({page}) => {
  test.skip(!process.env.EDITOR_LIVE_LAND,'Requires configured Editor land providers');
  test.setTimeout(90000);
  await page.goto('/land');
  await expect(page.getByRole('heading',{name:'대지 분석 통계'})).toBeVisible();
  await page.getByLabel('주소 또는 PNU').fill('1168011200101280003');
  await page.getByLabel('용도지역 직접 지정').selectOption({index:1});
  await page.getByLabel('법령 원문 검색').uncheck();
  const responsePromise=page.waitForResponse(r=>r.url().endsWith('/api/v1/land/analyze'),{timeout:70000});
  await page.locator('form').getByRole('button',{name:'대지 분석',exact:true}).click();
  const response=await responsePromise;
  expect(response.status()).toBe(200);
  const result=await response.json();
  expect(result.pnu.pnu).toBe('1168011200101280003');
  await expect(page.getByRole('heading',{name:'규제 요약',exact:true})).toBeVisible();
  expect(result.assessment.permit_compliance_verified).toBe(false);
  await expect(page.getByText('허가 적합성은 검증되지 않았습니다.',{exact:true})).toBeVisible();
  await page.screenshot({path:'test-results/editor-live-land.png',fullPage:true});
});

test('land analysis shows partial results and flat legal articles without hiding errors', async ({page}) => {
  await page.route('**/api/v1/land/zones',r=>r.fulfill({json:{zones:[{zone_name:'제2종일반주거지역',bcr_default:60,far_default:250}],count:1}}));
  await page.route('**/api/v1/land/stats*',r=>r.fulfill({json:{total_queries:1,error_count:0,avg_response_time_ms:2,by_input_type:[]}}));
  await page.route('**/api/v1/land/analyze',r=>{
    expect(r.request().postDataJSON()).toMatchObject({input:'1168011200101280003',input_type:'pnu',include_law:true});
    return r.fulfill({json:{pnu:{pnu:'1168011200101280003'},land_info:null,zone_info:null,
      regulations:{bcr:{limit_pct:60,article:'규제 근거'},extended:{x:{name:'추가 규제',rule:'확인 필요',article:'추가 근거'}}},
      law_articles:{articles:[{law_name:'시험 법령',article:'제1조',content:'검증용 법령 내용'}],total_count:1,errors:['검색 일부 실패']},
      restrictions:['도로 확인 필요'],errors:['필지 형상 미확인'],warning:'부분 분석 결과',
      assessment:{status:'needs_evidence',permit_compliance_verified:false,missing_evidence:['필요한 조례 근거']}}});
  });
  await page.goto('/land');
  await page.getByLabel('주소 또는 PNU').fill('1168011200101280003');
  await page.locator('form').getByRole('button',{name:'대지 분석',exact:true}).click();
  await expect(page.getByText('부분 분석 결과',{exact:true})).toBeVisible();
  await expect(page.getByText('필지 형상 미확인',{exact:true})).toBeVisible();
  await expect(page.getByText('검색 일부 실패',{exact:true})).toBeVisible();
  await expect(page.getByText('검증용 법령 내용',{exact:true})).toBeVisible();
  await expect(page.getByRole('heading',{name:'추가 규제',exact:true})).toBeVisible();
  await expect(page.getByText('허가 적합성은 검증되지 않았습니다.',{exact:true})).toBeVisible();
  await expect(page.getByText('필요한 조례 근거',{exact:true})).toBeVisible();
});

test('live execution through Editor form, worker and persisted history', async ({page}) => {
  test.skip(!process.env.EDITOR_LIVE_RUN_PROJECT, 'Requires isolated owner worker and project binding');
  test.setTimeout(120000);
  const projectId=process.env.EDITOR_LIVE_RUN_PROJECT!;
  await page.goto('/projects/'+projectId);
  await page.getByRole('button',{name:'기본 서비스 상태 점검',exact:true}).click();
  await page.getByRole('link',{name:'요청한 실행 열기'}).click();
  const url=page.url();
  await expect(page.getByTestId('run-status')).toHaveText('succeeded',{timeout:90000});
  await expect(page.locator('.agent-workspace li')).toHaveCount(3);
  await page.reload();
  await expect(page).toHaveURL(url);
  await expect(page.getByTestId('run-status')).toHaveText('succeeded');
  await page.screenshot({path:'test-results/editor-live-run.png',fullPage:true});
});

test('execution retry preserves request across reload and context changes', async ({page}) => {
  let version = 1;
  const requests: {key:string|null;body:unknown}[] = [];
  await page.route('**/api/v1/platform/projects/binding', route => route.fulfill({json:{
    project_id:'binding',owner_project_id:'p',branch_id:'main',scene_id:'scene',scene_revision:1,scene_project_id:null}}));
  await page.route('**/api/v1/platform/projects/binding/context', route => route.fulfill({json:{scene_revision:1,source_versions:{mass:version}}}));
  await page.route('**/api/v1/platform/projects/binding/runs', route => {
    if (route.request().method() === 'GET') return route.fulfill({json:[]});
    requests.push({key:route.request().headers()['idempotency-key'],body:route.request().postDataJSON()});
    return requests.length === 1 ? route.fulfill({status:503,json:{detail:'external_outcome_unknown'}})
      : route.fulfill({status:202,json:{run_id:'r',request_id:'k',owner_project_id:'p',branch_id:'main',goal:'health',status:'queued',receipt_task_ids:[],pending_input:false}});
  });
  await page.goto('/projects/binding');
  await page.getByRole('button',{name:'기본 서비스 상태 점검',exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('같은 요청');
  version = 2;
  await page.reload();
  await page.getByRole('button',{name:/기본 서비스 상태 점검|이전 요청 다시 확인/}).click();
  await expect(page.getByRole('link',{name:'요청한 실행 열기'})).toBeVisible();
  expect(requests).toHaveLength(2);
  expect(requests[1]).toEqual(requests[0]);
});

test('live project binding persists and rejects stale scene revision', async ({page}) => {
  test.skip(!process.env.EDITOR_LIVE_PROJECTS, 'Requires isolated project binding fixture');
  await page.goto('/projects');
  await page.getByLabel('설계 프로젝트 ID').fill('infra-probe');
  await page.getByLabel('브랜치 ID').fill('main');
  await page.getByLabel('장면 ID', {exact:true}).fill('platform-binding-20261004');
  await page.getByLabel('장면의 프로젝트 ID (미지정이면 비움)').fill('infra-probe');
  await page.getByLabel('장면 버전').fill('0');
  await page.getByRole('button', {name:'프로젝트 연결', exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('409');
  await page.getByLabel('장면 버전').fill('1');
  await page.getByRole('button', {name:'프로젝트 연결', exact:true}).click();
  await expect(page.getByRole('alert')).toHaveCount(0);
  await page.getByRole('link', {name:'infra-probe / main', exact:true}).click();
  await expect(page.getByRole('heading', {name:'infra-probe', exact:true})).toBeVisible();
  const url = page.url();
  await page.reload();
  await expect(page).toHaveURL(url);
  await expect(page.getByText('연결된 장면: platform-binding-20261004 · 기준 버전 1')).toBeVisible();
  await expect(page.getByRole('link', {name:'3D 장면 열기'})).toHaveAttribute('href','/editor/scene/platform-binding-20261004');
  await page.screenshot({path:'test-results/editor-live-project.png',fullPage:true});
});

test('live catalog through Editor backend and owner', async ({page, request}) => {
  test.skip(!process.env.EDITOR_LIVE_CATALOG, 'Requires separately started owner and Editor backend');
  const response = await request.get('/api/v1/platform/agents');
  expect(response.ok()).toBeTruthy();
  const agents = await response.json();
  expect(agents.length).toBeGreaterThan(0);
  await page.goto('/agents');
  await expect(page.locator('.agent-workspace article')).toHaveCount(agents.length);
  await expect(page.getByRole('alert')).toHaveCount(0);
  await page.screenshot({path:'test-results/editor-live-agents.png', fullPage:true});
});

test('routing: agent deep link, search, history and reload', async ({ page }) => {
  await page.route('**/api/v1/platform/agents', route => route.fulfill({json: [{
    agent_id: 'systems', label: 'Systems', capabilities: ['systems.review'],
    implementation_status: 'partial', connection_status: 'unknown', checked_at: null, evidence_ref: null,
  }]}));
  await page.goto('/agents');
  await expect(page.getByRole('heading', { name: 'Systems', exact: true })).toBeVisible();
  await expect(page.getByText('partial', { exact: true })).toBeVisible();
  await page.getByRole('textbox', {name:'에이전트 검색'}).fill('absent');
  await expect(page.getByText('검색 결과가 없습니다.')).toBeVisible();
  await page.getByRole('button', {name:'PLANM Planning'}).click();
  await expect(page).toHaveURL(/\/planm$/);
  await page.goBack();
  await expect(page).toHaveURL(/\/agents$/);
  await page.reload();
  await expect(page.getByRole('heading', {name:'Systems', exact:true})).toBeVisible();
});

test('routing: API failure never becomes empty success; retry recovers', async ({page}) => {
  let fail = true;
  await page.route('**/api/v1/platform/agents', route => fail
    ? route.fulfill({status:503, json:{detail:'unavailable'}})
    : route.fulfill({json:[]}));
  await page.goto('/agents');
  await expect(page.getByRole('alert')).toContainText('503');
  await expect(page.getByText('표시할 에이전트가 없습니다.')).toHaveCount(0);
  fail = false;
  await page.getByRole('button', {name:'새로고침'}).click();
  await expect(page.getByText('표시할 에이전트가 없습니다.')).toBeVisible();
});
