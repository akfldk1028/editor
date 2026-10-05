const { test, expect } = require('@playwright/test');

test('native Editor land route preserves the search UI and renders native response contracts', async ({ page }) => {
  await page.route('**/api/v1/land/zones', route => route.fulfill({ json: { zones: [{ zone_name: '제2종일반주거지역', bcr_default: 60, far_default: 250, category: '주거' }] } }));
  await page.route('**/api/v1/land/stats', route => route.fulfill({ json: { total_queries: 3, avg_response_time_ms: 20, error_count: 0, by_input_type: [] } }));
  await page.route('**/api/v1/land/analyze', async route => {
    expect(route.request().postDataJSON()).toMatchObject({ input: '1111010100100010000', input_type: 'pnu' });
    await route.fulfill({ json: {
      pnu: { pnu: '1111010100100010000' }, zone_info: { zones: ['제2종일반주거지역'], matched: 1, unmatched: [] },
      land_info: null, regulations: null, restrictions: ['적용 조례 증거 부족'], errors: ['법령 검색 연결 확인 필요'],
      law_articles: { articles: [{ hang_id: 'test', law_name: '검증용 법령', article: '제1조', content: '검증용 본문' }], total_count: 1, errors: [] }
    } });
  });
  const response = await page.goto(process.env.EDITOR_TEST_URL + '/land');
  expect(response.status()).toBe(200);
  await expect(page.getByRole('heading', { name: '토지 규제 분석' })).toBeVisible();
  await page.getByRole('textbox').fill('1111010100100010000');
  await page.getByRole('button', { name: '분석', exact: true }).click();
  await expect(page.getByText('제2종일반주거지역', { exact: true })).toBeVisible();
  await expect(page.getByText('법령 검색 연결 확인 필요', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: /관련 법조항/ }).click();
  await expect(page.getByText('검증용 본문')).toBeVisible();
  await page.screenshot({ path: 'test-results/native-land-results.png', fullPage: true });
  await page.reload();
  await expect(page.getByRole('heading', { name: '토지 규제 분석' })).toBeVisible();
  await page.screenshot({ path: process.env.EDITOR_SCREENSHOT || 'test-results/native-land.png', fullPage: true });
});

test('Editor navigation preserves the main UI and isolates workspace theme', async ({ page }) => {
  await page.goto(process.env.EDITOR_TEST_URL + '/');
  await expect(page.getByRole('link', { name: 'Open saved scenes' })).toBeVisible();
  await expect(page.locator('canvas').first()).toBeVisible({ timeout: 60_000 });
  await expect(page.locator('[class*="pascal-loader-"]')).toHaveCount(0, { timeout: 60_000 });
  const original = await page.locator('html').getAttribute('class');
  await page.evaluate(() => { window.__routeNavigationMarker = 'same-document'; });
  await page.locator('.editor-product-content').getByRole('link', { name: '토지 분석', exact: true }).click();
  await expect(page.getByRole('heading', { name: '토지 규제 분석' })).toBeVisible();
  await page.getByRole('button', { name: /다크 모드|라이트 모드/ }).click();
  expect(await page.locator('html').getAttribute('class')).toBe(original);
  await page.getByRole('complementary', { name: 'Main navigation' }).getByRole('link', { name: '3D Editor' }).click();
  await expect(page.getByRole('link', { name: 'Open saved scenes' })).toBeVisible();
  expect(await page.evaluate(() => window.__routeNavigationMarker)).toBe('same-document');
  await expect(page.locator('.agent-workspace')).toHaveCount(0);
  await expect(page.locator('canvas').first()).toBeVisible({ timeout: 60_000 });
  await expect(page.locator('[class*="pascal-loader-"]')).toHaveCount(0, { timeout: 60_000 });
  await page.screenshot({ path: 'test-results/native-editor-return.png', fullPage: true });
});

test('native proxy exposes backend failures and rejects cross-origin writes', async ({ request }) => {
  const root = process.env.EDITOR_TEST_URL;
  const zones = await request.get(root + '/api/v1/land/zones');
  expect(zones.status()).toBe(200);
  expect((await zones.json()).zones.length).toBeGreaterThan(0);
  const forbidden = await request.post(root + '/api/v1/land/analyze', { headers: { Origin: 'https://untrusted.example' }, data: { input: 'x', input_type: 'address' } });
  expect(forbidden.status()).toBe(403);
  expect((await request.get(root + '/api/v1/land/unknown')).status()).toBe(404);
  expect((await request.post(root + '/api/v1/land/stats', { data: {} })).status()).toBe(405);
});
