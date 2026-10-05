const { test, expect } = require('@playwright/test');
const base = process.env.EDITOR_TEST_URL || 'http://127.0.0.1:3003';

test('original law view retains search, result, article sidebar and map controls', async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const article = { hang_id: 'building::제60조', law_name: '건축법', law_type: '법률', article: '제60조', content: '건축물의 높이 제한 근거', similarity: 0.95, stages: [], source: 'test' };
  await page.route('**/api/v1/land/map-config', route => route.fulfill({ status: 503, json: { detail: '지도 오류 상태 검증' } }));
  await page.route('**/api/v1/law/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/health')) return route.fulfill({ json: { ready: true } });
    if (path.endsWith('/domains')) return route.fulfill({ json: { domains: [{ domain_id: 'building', domain_name: '건축', node_count: 1 }] } });
    if (path.endsWith('/article')) return route.fulfill({ json: { jo_prefix: article.hang_id, law_name: '건축법', law_type: '법률', jo: null, hangs: [{ full_id: article.hang_id, number: '①', content: '조문 원문 검증 내용', hos: [] }], hang_count: 1, ho_count: 0 } });
    return route.fulfill({ json: { results: [article], total_count: 1 } });
  });
  await page.goto(`${base}/law`);
  await expect(page.getByRole('heading', { name: '무엇을 찾고 계신가요?' })).toBeVisible({ timeout: 30000 });
  await expect(page.getByRole('button', { name: 'AI 심화 분석', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '건물 ON' }).click();
  await expect(page.getByRole('button', { name: '건물 OFF' })).toBeVisible();
  await page.getByRole('combobox', { name: '검색 도메인 선택' }).selectOption('building');
  await page.getByRole('textbox', { name: '법규 검색어 입력' }).fill('높이 제한');
  await page.getByRole('textbox', { name: '법규 검색어 입력' }).press('Enter');
  await expect(page.getByText(article.content, { exact: true })).toBeVisible();
  await page.getByText(article.content, { exact: true }).click();
  await expect(page.getByText('조문 원문 검증 내용', { exact: true })).toBeVisible();
  await expect.poll(async () => {
    const box = await page.getByRole('button', { name: '닫기' }).boundingBox();
    return box ? box.x + box.width : Infinity;
  }).toBeLessThanOrEqual(1440);
  await page.screenshot({ path: 'test-results/law-original-article.png' });
  await page.getByRole('button', { name: '닫기' }).click();
  await page.getByText('초기화', { exact: true }).click();
  await expect(page.getByRole('heading', { name: '무엇을 찾고 계신가요?' })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('heading', { name: '무엇을 찾고 계신가요?' })).toBeVisible();
  expect(errors).toEqual([]);
});

test('live VWorld 3D survives native route navigation', async ({ page }) => {
  test.skip(process.env.EDITOR_VERIFY_LIVE_VWORLD !== '1', 'Requires configured VWorld provider');
  await page.goto(`${base}/law`);
  await page.waitForFunction(() => window.ws3d?.viewer?.camera?.positionCartographic?.height < 10000, { }, { timeout: 45000 });
  await expect(page.locator('#vworld-3d-map-law canvas').first()).toBeVisible();
  await page.evaluate(() => { window.__lawNavigationProbe = true; });
  await page.screenshot({ path: 'test-results/law-live-vworld.png', timeout: 20000 });
  await page.getByRole('button', { name: '건물 ON' }).click();
  await expect(page.getByRole('button', { name: '건물 OFF' })).toBeVisible();
  await page.locator('.editor-product-content nav a[href="/map"]').click();
  await page.waitForURL('**/map');
  await page.locator('.editor-product-content nav a[href="/law"]').click();
  await page.waitForURL('**/law');
  await expect(page.locator('#vworld-3d-map-law canvas').first()).toBeVisible({ timeout: 15000 });
  expect(await page.evaluate(() => window.__lawNavigationProbe && window.ws3d.viewer.container.isConnected)).toBe(true);
  await page.screenshot({ path: 'test-results/law-live-vworld-return.png', timeout: 20000 });
});
