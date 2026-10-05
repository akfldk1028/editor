const { test, expect } = require('@playwright/test');
const base = process.env.EDITOR_TEST_URL || 'http://127.0.0.1:3003';
const project = { project_id: 'p1', owner_project_id: 'owner1', branch_id: 'main', scene_id: 'scene1', scene_revision: 1, scene_project_id: null };
const ownerRequest = { goal: 'specialist_review', specialist_reviews: [{ agent: 'systems', tool: 'systems_requirements', args: { request: { project_id: 'owner1', branch_id: 'main', source_refs: [{ id: 'program', path: 'fixtures/real-program.json' }] } }, source_versions: { 'program.spaces': 3 } }] };
const run = { run_id: 'review1', request_id: '', owner_project_id: 'owner1', branch_id: 'main', goal: 'specialist_review', status: 'blocked', receipt_task_ids: [], pending_input: false };
const upload = (page, value) => page.getByLabel('담당 에이전트 검토 요청 파일').setInputFiles({ name: 'owner-review.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(value)) });

async function setup(page) {
  await page.route('**/api/v1/platform/projects', r => r.fulfill({ json: [project, { ...project, project_id: 'p2', owner_project_id: 'owner2', scene_id: 'scene2' }] }));
  await page.route('**/api/v1/platform/projects/*/runs', r => r.fulfill({ json: [] }));
  await page.route('**/api/v1/platform/projects/*/context', r => r.fulfill({ json: { scene_revision: 1, source_versions: { 'program.spaces': 3 } } }));
  await page.goto(`${base}/dialogue?project_id=p1`);
}

test('specialist review imports readable sources and retries identical frozen body after reload', async ({ page }) => {
  await setup(page);
  const submissions = [];
  let contextReads = 0;
  await page.route('**/api/v1/platform/projects/p1/context', r => { contextReads++; return r.fulfill({ json: { scene_revision: 1, source_versions: { 'program.spaces': 3 } } }); });
  await page.route('**/api/v1/platform/projects/p1/runs', r => {
    if (r.request().method() === 'GET') return r.fulfill({ json: [] });
    submissions.push({ key: r.request().headers()['idempotency-key'], body: r.request().postData() });
    return r.fulfill(submissions.length === 1 ? { status: 503, json: { detail: 'external_outcome_unknown' } } : { status: 202, json: { ...run, request_id: `editor:p1:${submissions[0].key}` } });
  });
  await page.route('**/api/v1/platform/runs/review1?project_id=p1', r => r.fulfill({ json: run }));
  await upload(page, ownerRequest);
  await expect(page.getByTestId('specialist-review-preview')).toContainText('systems_requirements');
  await expect(page.getByTestId('specialist-review-preview')).toContainText('program.spaces · r3');
  await expect(page.getByTestId('specialist-review-preview')).toContainText('fixtures/real-program.json');
  await page.getByRole('button', { name: '담당 에이전트 검토 실행', exact: true }).click();
  await expect(page.getByRole('alert').filter({ hasText: '접수 여부를 확인하지 못했습니다' })).toBeVisible();
  await page.reload();
  await page.getByRole('button', { name: '같은 검토 요청 재확인', exact: true }).click();
  await expect(page).toHaveURL(/project_id=p1&run_id=review1$/, { timeout: 30000 });
  expect(submissions).toHaveLength(2);
  expect(submissions[1]).toEqual(submissions[0]);
  expect(JSON.parse(submissions[0].body).request).toEqual(ownerRequest);
  expect(contextReads).toBe(1);
});

test('review preview distinguishes captured context from supplied source versions and assets', async ({ page }) => {
  await setup(page);
  const supplied = structuredClone(ownerRequest);
  Object.assign(supplied.specialist_reviews[0].args.request, {
    expected_source_versions: { 'program.snapshot': 2 },
    source_identity: { project: 'owner1', branch: 'main' },
    source_assets: [{ role: 'mass', path: 'assets/retained.glb', sha256: 'a'.repeat(64), selection_status: 'retained' }],
  });
  await upload(page, supplied);
  const preview = page.getByTestId('specialist-review-preview');
  await expect(preview).toContainText('program.spaces · r3');
  await expect(preview).toContainText('program.snapshot: 2');
  await expect(preview).toContainText('assets/retained.glb');
  await expect(preview).toContainText('a'.repeat(64));
  await expect(preview).toContainText('입력 자료의 선언 버전');
});

test('uncertain POST remains scoped to original project when its delayed reply arrives', async ({ page }) => {
  await setup(page);
  let enter;
  let release;
  const started = new Promise(resolve => { enter = resolve; });
  const gate = new Promise(resolve => { release = resolve; });
  const submissions = [];
  await page.route('**/api/v1/platform/projects/p1/runs', async r => {
    if (r.request().method() === 'GET') return r.fulfill({ json: [] });
    submissions.push({ key: r.request().headers()['idempotency-key'], body: r.request().postData() });
    if (submissions.length === 1) { enter(); await gate; }
    await r.fulfill({ status: 202, json: { ...run, request_id: `editor:p1:${submissions[0].key}` } }).catch(() => {});
  });
  await page.route('**/api/v1/platform/runs/review1?project_id=p1', r => r.fulfill({ json: run }));
  await upload(page, ownerRequest);
  await page.getByRole('button', { name: '담당 에이전트 검토 실행', exact: true }).click();
  await started;
  await page.getByLabel('프로젝트 선택', { exact: true }).selectOption('p2');
  await expect(page).toHaveURL(/project_id=p2$/);
  release();
  await expect(page.getByRole('button', { name: '담당 에이전트 검토 실행', exact: true })).toBeDisabled();
  await page.getByLabel('프로젝트 선택', { exact: true }).selectOption('p1');
  await page.getByRole('button', { name: '같은 검토 요청 재확인', exact: true }).click();
  await expect(page).toHaveURL(/project_id=p1&run_id=review1$/, { timeout: 30000 });
  expect(submissions).toHaveLength(2);
  expect(submissions[1]).toEqual(submissions[0]);
});

test('review is not posted when the pending receipt cannot be saved', async ({ page }) => {
  await page.addInitScript(() => {
    const set = Storage.prototype.setItem;
    Storage.prototype.setItem = function(key, value) { if (key.startsWith('editor:pending-specialist:')) throw new Error('quota'); return set.call(this, key, value); };
  });
  await setup(page);
  let posts = 0;
  await page.route('**/api/v1/platform/projects/p1/runs', r => { if (r.request().method() === 'POST') posts++; return r.fulfill({ json: [] }); });
  await upload(page, ownerRequest);
  await page.getByRole('button', { name: '담당 에이전트 검토 실행', exact: true }).click();
  await expect(page.getByRole('alert').filter({ hasText: '저장하지 못해 검토를 보내지 않았습니다' })).toBeVisible();
  expect(posts).toBe(0);
});

test('specialist import refuses authoring and other-project inputs then rejects changed revisions before posting', async ({ page }) => {
  await setup(page);
  let posts = 0;
  await page.route('**/api/v1/platform/projects/p1/runs', r => { if (r.request().method() === 'POST') posts++; return r.fulfill({ json: [] }); });
  await upload(page, { goal: 'interior_concept', specialist_reviews: [] });
  await expect(page.getByRole('alert').filter({ hasText: '읽기 전용 전문 검토 요청' })).toBeVisible();
  const other = structuredClone(ownerRequest);
  other.specialist_reviews[0].args.request.project_id = 'owner2';
  await upload(page, other);
  await expect(page.getByRole('alert').filter({ hasText: '선택한 프로젝트' })).toBeVisible();
  const stale = structuredClone(ownerRequest);
  stale.specialist_reviews[0].source_versions['program.spaces'] = 2;
  await upload(page, stale);
  await page.getByRole('button', { name: '담당 에이전트 검토 실행', exact: true }).click();
  await expect(page.getByRole('alert').filter({ hasText: '원본 버전이 달라' })).toBeVisible();
  expect(posts).toBe(0);
});

test('project switch ignores delayed specialist context and never submits the old project', async ({ page }) => {
  await setup(page);
  let release;
  let entered;
  const started = new Promise(resolve => { entered = resolve; });
  const gate = new Promise(resolve => { release = resolve; });
  await page.route('**/api/v1/platform/projects/p1/context', async r => { entered(); await gate; await r.fulfill({ json: { scene_revision: 1, source_versions: { 'program.spaces': 3 } } }).catch(() => {}); });
  const posts = [];
  await page.route('**/api/v1/platform/projects/*/runs', r => { if (r.request().method() === 'POST') posts.push(r.request().url()); return r.fulfill({ json: [] }); });
  await upload(page, ownerRequest);
  await page.getByRole('button', { name: '담당 에이전트 검토 실행', exact: true }).click();
  await started;
  await page.getByLabel('프로젝트 선택', { exact: true }).selectOption('p2');
  await expect(page).toHaveURL(/project_id=p2$/);
  release();
  await expect(page.getByRole('link', { name: '현재 프로젝트 3D 장면 열기' })).toHaveAttribute('href', '/scene/scene2');
  await expect(page.getByRole('button', { name: '담당 에이전트 검토 실행', exact: true })).toBeDisabled();
  expect(posts).toEqual([]);
});
