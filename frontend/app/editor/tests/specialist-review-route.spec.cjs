const { test, expect } = require('@playwright/test');
const base = process.env.EDITOR_TEST_URL || 'http://127.0.0.1:3003';
const project = { project_id: 'p1', owner_project_id: 'owner1', branch_id: 'main', scene_id: 'scene1', scene_revision: 1, scene_project_id: null };
const ownerRequest = { goal: 'specialist_review', specialist_reviews: [{ agent: 'systems', tool: 'systems_requirements', args: { request: { project_id: 'owner1', branch_id: 'main', source_refs: [{ id: 'program', path: 'fixtures/real-program.json' }] } }, source_versions: { 'program.spaces': 3 } }] };
const run = { run_id: 'review1', request_id: '', owner_project_id: 'owner1', branch_id: 'main', goal: 'specialist_review', status: 'blocked', receipt_task_ids: [], pending_input: false };
const upload = (page, value) => page.getByLabel('담당 에이전트 검토 요청 파일').setInputFiles({ name: 'owner-review.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(value)) });

test('scene binding refresh previews saved revision and explicitly advances the same binding', async ({ page }) => {
  let current = { ...project };
  const changes = [];
  await page.route('**/api/v1/platform/projects', r => r.fulfill({ json: [current] }));
  await page.route('**/api/v1/platform/projects/p1/runs', r => r.fulfill({ json: [] }));
  await page.route('**/api/scenes/scene1', r => r.fulfill({ json: { id: 'scene1', projectId: null, version: 3 } }));
  await page.route('**/api/v1/platform/projects/p1/scene-revision', r => {
    changes.push(r.request().postDataJSON());
    current = { ...current, scene_revision: 3 };
    return r.fulfill({ json: current });
  });
  await page.goto(`${base}/dialogue?project_id=p1`);
  const section = page.getByRole('region', { name: '장면 버전 연결' });
  await section.getByRole('button', { name: '저장된 장면 버전 확인' }).click();
  await expect(section).toContainText('저장된 버전: 3');
  expect(changes).toEqual([]);
  await section.getByRole('button', { name: '버전 3 연결 갱신' }).click();
  await expect(section).toContainText('연결된 장면 버전: 3');
  expect(changes).toEqual([{ expected_scene_revision: 1, scene_revision: 3 }]);
});

test('scene binding refresh rejects an unrelated saved scene without offering a write', async ({ page }) => {
  await setup(page);
  await page.route('**/api/scenes/scene1', r => r.fulfill({ json: { id: 'foreign', projectId: null, version: 3 } }));
  const section = page.getByRole('region', { name: '장면 버전 연결' });
  await section.getByRole('button', { name: '저장된 장면 버전 확인' }).click();
  await expect(section.getByRole('alert')).toBeVisible();
  await expect(section.getByRole('button', { name: /연결 갱신/ })).toHaveCount(0);
});

async function setup(page) {
  await page.route('**/api/v1/platform/projects', r => r.fulfill({ json: [project, { ...project, project_id: 'p2', owner_project_id: 'owner2', scene_id: 'scene2' }] }));
  await page.route('**/api/v1/platform/projects/*/runs', r => r.fulfill({ json: [] }));
  await page.route('**/api/v1/platform/projects/*/context', r => r.fulfill({ json: { scene_revision: 1, source_versions: { 'program.spaces': 3 } } }));
  await page.goto(`${base}/dialogue?project_id=p1`);
}

test('owner dialogue prepares a follow-up proposal without another JSON upload or loss of long sources', async ({ page }) => {
  const previous = { ...run, run_id: 'previous', request_id: 'editor:p1:previous', communications: [], communications_available: true, communications_truncated: false };
  const source = 'Retained owner source '.repeat(800);
  const request = { goal: 'specialist_review', specialist_reviews: [{ agent: 'domain_expert', tool: 'domain_review', source_versions: { 'program.spaces': 3 }, args: { request: {
    project_id: 'owner1', branch_id: 'main', declared_domain: '', requirements: [], evidence: [],
    sources: [{ id: 'program', content: source, dirty: true, quality: 'needs_evidence' }],
  } } }] };
  await page.route('**/api/v1/platform/projects', route => route.fulfill({ json: [project] }));
  await page.route('**/api/v1/platform/projects/p1/context', route => route.fulfill({ json: { scene_revision: 1, source_versions: { 'program.spaces': 3 } } }));
  await page.route('**/api/v1/platform/runs/previous?project_id=p1', route => route.fulfill({ json: previous }));
  await page.route('**/api/v1/platform/runs/previous/request?project_id=p1', route => route.fulfill({ json: { ...previous,
    request, source_versions: { 'program.spaces': 3 }, reviews: [{ agent: 'domain_expert', tool: 'domain_review', state: 'blocked', task_id: 'actual-owner-task', needs: ['Clarify the intended use and proposed circulation'], needs_truncated: false }],
  } }));
  const submissions = [];
  await page.route('**/api/v1/platform/projects/p1/runs', route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: [previous] });
    submissions.push(route.request().postDataJSON());
    return route.fulfill({ status: 503, json: { detail: 'external_outcome_unknown' } });
  });
  await page.goto(`${base}/dialogue?project_id=p1&run_id=previous`);
  await page.getByRole('button', { name: '이 실행에서 대화 이어가기' }).click();
  await expect(page.getByTestId('followup-review-draft')).toContainText('Clarify the intended use');
  await page.getByLabel('검토할 용도·운영 방향').fill('Proposed public office');
  await page.getByLabel('함께 검토할 제안·조건').fill('Separate visitor circulation from staff work');
  await page.getByRole('button', { name: '후속 검토 요청 준비' }).click();
  await expect(page.getByRole('button', { name: '담당 에이전트 검토 실행', exact: true })).toBeEnabled();
  await page.getByLabel('함께 검토할 제안·조건').fill('Separate visitor circulation from staff work\nReview accessible entrances');
  await expect(page.getByRole('button', { name: '담당 에이전트 검토 실행', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: '후속 검토 요청 준비' }).click();
  await page.getByRole('button', { name: '담당 에이전트 검토 실행', exact: true }).click();
  await expect.poll(() => submissions.length).toBe(1);
  const submitted = submissions[0].request.specialist_reviews[0].args.request;
  expect(submitted.sources[0].content).toBe(source);
  expect(submitted.sources[0].dirty).toBe(true);
  expect(submitted.requirements[0].statement).toBe('Separate visitor circulation from staff work');
  expect(submitted.requirements[0].provenance.professionally_verified).toBe(false);
  expect(submitted.evidence).toEqual([]);
  await expect(page.getByRole('button', { name: '후속 검토 요청 준비' })).toBeDisabled();
});

test('resumed Systems dialogue keeps the previous owner catalog choices', async ({ page }) => {
  await setup(page);
  const submissions = [];
  await page.route('**/api/v1/platform/projects/p1/runs', route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: [] });
    submissions.push(route.request().postDataJSON());
    return route.fulfill({ status: 503, json: { detail: 'external_outcome_unknown' } });
  });
  const previous = { ...run, run_id: 'catalog', request_id: 'editor:p1:catalog' };
  await page.route('**/api/v1/platform/runs/catalog?project_id=p1', route => route.fulfill({ json: previous }));
  await page.route('**/api/v1/platform/runs/catalog/request?project_id=p1', route => route.fulfill({ json: {
    ...previous, source_versions: { 'program.spaces': 3 }, reviews: [], request: {
      goal: 'specialist_review', specialist_reviews: [{ agent: 'systems', tool: 'systems_requirements', source_versions: { 'program.spaces': 3 },
        args: { request: { schema_version: 'systems.use.catalog.request.v1', operational_type: 'government_office', functional_type: 'staff_workroom' } } }],
    },
  } }));
  await page.goto(`${base}/dialogue?project_id=p1&run_id=catalog`);
  await page.getByRole('button', { name: '이 실행에서 대화 이어가기' }).click();
  await expect(page.getByLabel('운영 용도 코드 (선택)')).toHaveValue('government_office');
  await expect(page.getByLabel('공간 기능 코드 (선택)')).toHaveValue('staff_workroom');
  await page.getByRole('button', { name: '후속 검토 요청 준비' }).click();
  await page.getByRole('button', { name: '담당 에이전트 검토 실행', exact: true }).click();
  await expect.poll(() => submissions.length).toBe(1);
  expect(submissions[0].request.specialist_reviews[0].args.request).toEqual({
    schema_version: 'systems.use.catalog.request.v1', operational_type: 'government_office', functional_type: 'staff_workroom',
  });
});

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
