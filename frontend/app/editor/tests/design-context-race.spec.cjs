const { test, expect } = require('@playwright/test');
const base = process.env.EDITOR_TEST_URL || 'http://127.0.0.1:3003';

test('a delayed boundary uses the currently selected building type for legal context', async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  let boundaryRoute;
  const analyses = [];
  await page.route(/\/api\/v1\/design\/site-boundary\/?$/, route => { boundaryRoute = route; });
  await page.route('**/api/v1/land/analyze', async route => {
    analyses.push(route.request().postDataJSON());
    await route.fulfill({ json: { regulations: { bcr: { limit_pct: 60 } }, zone_info: { zones: [] } } });
  });
  await page.goto(`${base}/design?pnu=1168010100106770000`);
  await expect(page.getByText('MAAS Legal Morphology Search', { exact: true })).toBeVisible({ timeout: 60000 });
  expect(errors).toEqual([]);
  await expect.poll(() => Boolean(boundaryRoute), { timeout: 30000 }).toBe(true);
  const building = page.locator('select').first();
  await building.selectOption({ index: 2 });
  const selected = await building.inputValue();
  await boundaryRoute.fulfill({ json: { pnu: '1168010100106770000', area_m2: 100,
    geometry: { type: 'Polygon', coordinates: [[[127,37.5],[127.001,37.5],[127.001,37.501],[127,37.5]]] } } });
  await expect.poll(() => analyses.length).toBe(1);
  expect(analyses[0].building_type).toBe(selected);
});
