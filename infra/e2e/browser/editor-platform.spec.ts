import { test, expect } from '@playwright/test';

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
