const { test, expect } = require('@playwright/test');
const base = process.env.EDITOR_TEST_URL || 'http://127.0.0.1:3003';

test('original design panels, tabs, graph and navigation render in Editor', async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(`${base}/design`);
  await expect(page.getByRole('heading', { name: '건물 매스 최적화' })).toBeVisible({ timeout: 30000 });
  await expect(page.getByPlaceholder('PNU 코드 (19자리) 또는 주소')).toBeVisible();
  await page.getByRole('button', { name: '평면', exact: true }).click();
  await expect(page.getByRole('button', { name: '자동 ON', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '자동 ON', exact: true }).click();
  await expect(page.getByRole('button', { name: '자동 OFF', exact: true })).toBeVisible();
  await page.getByTestId('design-ai-collaboration-toggle').click();
  await expect(page.getByTestId('design-ai-collaboration-panel')).toHaveAttribute('data-collapsed', 'true');
  await page.getByTestId('design-ai-collaboration-toggle').click();
  await page.getByRole('link', { name: '설계 언어 · 실행 근거', exact: true }).click();
  await expect(page).toHaveURL(`${base}/design/language`, { timeout: 30000 });
  await expect(page.locator('.book-network__node').first()).toBeVisible({ timeout: 30000 });
  for (const tab of ['MASS ARCHIVE', 'MASS PORTFOLIO', 'SELECTED MASS PATH', 'FULL GRAPH']) {
    await page.getByRole('tab', { name: tab, exact: true }).click();
    await expect(page.getByRole('tab', { name: tab, exact: true })).toHaveAttribute('aria-selected', 'true');
  }
  await page.screenshot({ path: 'test-results/design-language-native.png', fullPage: true });
  expect(errors).toEqual([]);
});

test('design uses the live shared VWorld viewer and survives route return', async ({ page }) => {
  test.skip(process.env.EDITOR_VERIFY_LIVE_VWORLD !== '1');
  await page.goto(`${base}/design`);
  await expect(page.locator('.cesium-widget canvas')).toBeVisible({ timeout: 60000 });
  await page.evaluate(() => { window.__designRouteReturnMarker = true; });
  await page.screenshot({ path: 'test-results/design-live-vworld.png', fullPage: true });
  await page.getByRole('link', { name: '설계 언어 · 실행 근거', exact: true }).click();
  await expect(page).toHaveURL(`${base}/design/language`, { timeout: 30000 });
  await page.getByRole('link', { name: '매스 · 평면 설계', exact: true }).click();
  await expect(page).toHaveURL(`${base}/design`, { timeout: 30000 });
  await expect(page.locator('.cesium-widget canvas')).toBeVisible({ timeout: 30000 });
  expect(await page.evaluate(() => window.__designRouteReturnMarker)).toBe(true);
});

test('native design archive displays preserved images without promoting them to new runs', async ({ page, request }) => {
  const response = await request.get(`${base}/api/v1/design/maas/executed-masses`);
  expect(response.ok()).toBe(true);
  const archive = await response.json();
  expect(archive.editor_provenance.execution_verified).toBe(false);
  expect(archive.runs.length).toBeGreaterThan(0);
  await page.goto(`${base}/design/language`);
  await expect(page.locator('.book-network__node').first()).toBeVisible({ timeout: 30000 });
  await expect.poll(async () => page.locator('img').evaluateAll(images => images.filter(image => image.src.includes('/api/v1/design/maas/executed-masses/') && image.complete && image.naturalWidth > 0).length), { timeout: 30000 }).toBeGreaterThan(0);
  const imageRuns = await page.locator('img').evaluateAll(images => images.filter(image => image.src.includes('/api/v1/design/maas/executed-masses/')).map(image => new URL(image.src).searchParams.get('run_id')));
  expect(imageRuns).toContain(archive.selected_run_id);
  await page.reload();
  await expect(page.locator('.book-network__node').first()).toBeVisible({ timeout: 30000 });
});
