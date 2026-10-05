const { test, expect } = require('@playwright/test');
const project = { project_id: 'p1', owner_project_id: 'owner1', branch_id: 'main', scene_id: 'scene1', scene_revision: 0, scene_project_id: null };
const run = { run_id: 'r1', request_id: 'req1', owner_project_id: 'owner1', branch_id: 'main', goal: 'health', status: 'partial', receipt_task_ids: ['t1'], pending_input: true,
  communications_available: true, communications_truncated: false, communications: [
    { id: 'c1', task_id: 't1', tool: 'health', agent: 'systems', state: 'blocked', request_text: '설비 연결 확인', response_text: '연결 설정이 필요합니다.', transport: 'a2a', truncated: false },
    { id: 'c2', task_id: 't2', tool: 'health', agent: 'law', state: 'completed', request_text: '법규 연결 확인', response_text: '연결 응답', transport: 'unknown', truncated: false },
  ] };

test('original MAS panel renders project-bound records, filters, payloads, reload and unavailable state', async ({ page }) => {
  let unavailable = false;
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.route('**/api/v1/platform/projects', r => r.fulfill({ json: [project] }));
  await page.route('**/api/v1/platform/projects/p1/runs', r => r.fulfill({ json: [run] }));
  await page.route('**/api/v1/platform/runs/r1?project_id=p1', r => r.fulfill(unavailable ? { status: 503, json: { detail: 'Owner unavailable' } } : { json: run }));
  await page.goto(process.env.EDITOR_TEST_URL + '/dialogue?project_id=p1&run_id=r1');
  await expect(page.getByText('설비 연결 확인', { exact: true })).toBeVisible();
  await page.getByRole('combobox', { name: '대화 에이전트 필터' }).selectOption('systems');
  await expect(page.getByText('법규 연결 확인', { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: /기록 메타데이터 \(JSON\) 보기/ }).first().click();
  await expect(page.locator('pre')).toContainText('"task_id": "t1"');
  await expect(page.getByText('60.0% / 59.98%')).toHaveCount(0);
  await expect(page.getByText('PASS', { exact: true })).toHaveCount(0);
  await page.screenshot({ path: 'test-results/native-agent-dialogue.png', fullPage: true });
  await page.reload();
  await expect(page.getByText('설비 연결 확인', { exact: true })).toBeVisible();
  unavailable = true;
  await page.getByRole('button', { name: '새로고침', exact: true }).click();
  await expect(page.getByRole('alert').filter({ hasText: '실행 연결 실패 (503)' })).toBeVisible();
  await expect(page.getByText('설비 연결 확인', { exact: true })).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('dialogue rejects a run belonging to a different owner instead of displaying it', async ({ page, request }) => {
  await page.route('**/api/v1/platform/projects', r => r.fulfill({ json: [project] }));
  await page.route('**/api/v1/platform/projects/p1/runs', r => r.fulfill({ json: [] }));
  await page.route('**/api/v1/platform/runs/r1?project_id=p1', r => r.fulfill({ json: { ...run, owner_project_id: 'other-owner' } }));
  await page.goto(process.env.EDITOR_TEST_URL + '/dialogue?project_id=p1&run_id=r1');
  await expect(page.getByRole('alert').filter({ hasText: '프로젝트와 실행 연결이 일치하지 않습니다.' })).toBeVisible();
  await expect(page.getByText('설비 연결 확인', { exact: true })).toHaveCount(0);
  expect((await request.get(process.env.EDITOR_TEST_URL + '/api/v1/platform/arbitrary-service')).status()).toBe(404);
  expect((await request.post(process.env.EDITOR_TEST_URL + '/api/v1/platform/agents', { data: {} })).status()).toBe(404);
});

test('connection check submits once and retries the identical request before opening its dialogue', async ({ page }) => {
  const submissions = [];
  let accepted = false;
  let contextReads = 0;
  await page.route('**/api/v1/platform/projects', r => r.fulfill({ json: [project] }));
  await page.route('**/api/v1/platform/projects/p1/context', r => { contextReads++; return r.fulfill({ json: { scene_revision: 0, source_versions: { site: 2 } } }); });
  await page.route('**/api/v1/platform/projects/p1/runs', r => {
    if (r.request().method() === 'GET') return r.fulfill({ json: accepted ? [run] : [] });
    submissions.push({ key: r.request().headers()['idempotency-key'], body: r.request().postDataJSON() });
    if (submissions.length === 1) return r.fulfill({ status: 503, json: { detail: 'external_outcome_unknown' } });
    accepted = true;
    return r.fulfill({ status: 202, json: { ...run, request_id: `editor:p1:${submissions[0].key}` } });
  });
  await page.route('**/api/v1/platform/runs/r1?project_id=p1', r => r.fulfill({ json: run }));
  await page.goto(process.env.EDITOR_TEST_URL + '/dialogue?project_id=p1');
  await page.getByRole('button', { name: '에이전트 연결 점검 실행' }).click();
  await expect(page.getByRole('alert')).toContainText('실행 접수 여부를 확인하지 못했습니다.');
  await page.reload();
  await page.getByRole('button', { name: '같은 연결 점검 요청 재확인' }).click();
  await expect(page).toHaveURL(/\/dialogue\?project_id=p1&run_id=r1$/);
  await expect(page.getByText('설비 연결 확인', { exact: true })).toBeVisible();
  expect(submissions).toHaveLength(2);
  expect(submissions[1]).toEqual(submissions[0]);
  expect(contextReads).toBe(1);
});
