const { test, expect } = require('@playwright/test');
test('original project view is available with the native binding and scene link', async ({ page }) => {
  await page.goto(process.env.EDITOR_TEST_URL + '/projects');
  await expect(page.getByRole('heading', { name: '프로젝트', exact: true })).toBeVisible();
  await page.locator('a[href="/projects/6c92d0cfe54d44cab465c00f6f59d04c"]').click();
  await expect(page.getByRole('heading', { name: '저장된 설계', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: '신규 설계 명세', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: '보관된 실행 자료', exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: '3D 장면 열기' })).toHaveAttribute('href', '/scene/uijeongbu-r39-source-mass3');
});

test('original run view uses the requested project binding and rejects foreign results', async ({ page }) => {
  const project = { project_id: 'native-binding', owner_project_id: 'owner-model', branch_id: 'main', scene_id: 'scene', scene_revision: 2, scene_project_id: null };
  const run = { run_id: 'run1', request_id: 'editor:native-binding:request', owner_project_id: 'owner-model', branch_id: 'main', goal: 'specialist_review', status: 'completed', receipt_task_ids: [], pending_input: false,
    communications_available: true, communications_truncated: false, communications: [] };
  let foreign = false;
  await page.route('**/api/v1/platform/projects/native-binding', route => route.fulfill({ json: project }));
  await page.route('**/api/v1/platform/runs/run1?project_id=native-binding', route => route.fulfill({ json: { ...run, owner_project_id: foreign ? 'other-owner' : run.owner_project_id } }));
  await page.goto(process.env.EDITOR_TEST_URL + '/runs/run1?project_id=native-binding');
  await expect(page.getByTestId('run-status')).toHaveText('completed');
  await expect(page.getByRole('link', { name: '프로젝트로 돌아가기' })).toHaveAttribute('href', '/projects/native-binding');
  foreign = true;
  await page.reload();
  await expect(page.getByRole('alert').filter({ hasText: '프로젝트와 실행 연결이 일치하지 않습니다.' })).toBeVisible();
  await expect(page.getByTestId('run-status')).toHaveCount(0);
  await page.goto(process.env.EDITOR_TEST_URL + '/runs/run1');
  await expect(page.getByRole('alert').filter({ hasText: '프로젝트 연결이 없는 실행 주소입니다.' })).toBeVisible();
});

test('project route rejects owner ID substituted for the binding ID', async ({ page }) => {
  await page.route('**/api/v1/platform/projects/native-binding', route => route.fulfill({ json: {
    project_id: 'owner-model', owner_project_id: 'owner-model', branch_id: 'main', scene_id: 'scene', scene_revision: 2, scene_project_id: null,
  } }));
  await page.goto(process.env.EDITOR_TEST_URL + '/projects/native-binding');
  await expect(page.getByRole('alert').filter({ hasText: '요청한 프로젝트와 응답의 연결 ID가 일치하지 않습니다.' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '신규 설계 명세', exact: true })).toHaveCount(0);
});
test('product header restores CAD and PLANM on the Editor origin', async ({ page }) => {
  await page.goto(process.env.EDITOR_TEST_URL + '/dialogue');
  const nav = page.getByRole('navigation', { name: '제품 작업 공간' });
  await expect(nav.getByRole('link', { name: 'CAD · DWG', exact: true })).toBeVisible();
  await nav.getByRole('link', { name: 'CAD · DWG', exact: true }).click();
  await expect(page).toHaveURL(/\/dwg$/);
  await expect(nav.getByRole('link', { name: 'CAD · DWG', exact: true })).toHaveAttribute('aria-current', 'page');
  await expect(page.getByText('Drawing review', { exact: true })).toBeVisible();
  await page.screenshot({ path: 'test-results/native-cad-navigation.png', fullPage: true });
  await nav.getByRole('link', { name: 'PLANM 평면 계획', exact: true }).click();
  await expect(page).toHaveURL(/\/planm$/);
  await expect(page.locator('.planm-surface')).toBeVisible();
  await nav.getByRole('link', { name: '3D Editor', exact: true }).click();
  await expect(page).toHaveURL(new RegExp(process.env.EDITOR_TEST_URL + '/$'));
  await expect(nav.getByRole('link', { name: '3D Editor', exact: true })).toHaveAttribute('aria-current', 'page');
  await expect(page.locator('canvas').first()).toBeVisible({ timeout: 30000 });
});

test('CAD and PLANM proxies reach owned services and reject unrelated operations', async ({ request }) => {
  const base = process.env.EDITOR_TEST_URL;
  const drawing = await request.get(base + '/api/drawing');
  expect(drawing.status()).toBe(200);
  expect((await drawing.json()).entities.length).toBeGreaterThan(0);
  const missing = await request.get(base + '/api/v1/planm/runs/nonexistent-navigation-fixture');
  expect(missing.status()).toBe(404);
  expect((await missing.json()).detail).toBeTruthy();
  const selection = await request.get(base + '/api/v1/platform/projects/6c92d0cfe54d44cab465c00f6f59d04c/design/selection/mass');
  expect(selection.status()).toBe(404);
  expect((await selection.json()).detail).toBe('No saved design selection');
  expect((await request.post(base + '/api/v1/platform/projects/6c92d0cfe54d44cab465c00f6f59d04c/design/selection/mass')).status()).toBe(404);
  expect((await request.get(base + '/api/arbitrary-service')).status()).toBe(404);
  expect((await request.post(base + '/api/v1/planm/runs/invalid/delete')).status()).toBe(404);
  expect((await request.post(base + '/api/edit/apply', { headers: { origin: 'https://other.invalid' }, data: {} })).status()).toBe(403);
  expect((await request.post(base + '/api/v1/platform/projects/native-binding/design/native-jobs', { headers: { origin: 'https://other.invalid' }, data: {} })).status()).toBe(403);
});

test('saved native scene retains product navigation', async ({ page }) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  const assetLoaded = page.waitForResponse(response => /\/api\/v1\/platform\/scene-assets\/[a-f0-9]{64}\.glb$/.test(response.url()), { timeout: 30000 });
  await page.goto(process.env.EDITOR_TEST_URL + '/scene/uijeongbu-r39-source-mass3');
  const nav = page.getByRole('navigation', { name: '제품 작업 공간' });
  await expect(nav.getByRole('link', { name: '저장된 장면', exact: true })).toHaveAttribute('aria-current', 'page');
  await expect(page.locator('canvas').first()).toBeVisible({ timeout: 30000 });
  const asset = await assetLoaded;
  expect(asset.status()).toBe(200);
  const bytes = await asset.body();
  expect(bytes.subarray(0, 4).toString()).toBe('glTF');
  await page.locator('button').filter({ has: page.locator('img[src*="scene.webp"]') }).click();
  await expect(page.getByText('No buildings yet', { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Camera snapshot', exact: true }).first().click();
  await page.getByText('View snapshot', { exact: true }).click();
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  expect(pageErrors).toEqual([]);
  await expect(nav.getByRole('link', { name: 'CAD · DWG', exact: true })).toBeVisible();
});
