const { test, expect } = require('@playwright/test');

test('original map route renders its map, search and analysis panel through native APIs', async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/v1/land/tiles/**', route => route.fulfill({ status: 503, json: { detail: 'Map provider is not configured' } }));
  await page.route('**/api/v1/land/wms?**', route => route.fulfill({ status: 503, json: { detail: 'Map provider is not configured' } }));
  await page.route('**/api/v1/land/parcel-geometry', route => route.fulfill({ json: { success: false, geometry: null, error: '필지 경계 공급자 미설정' } }));
  await page.route('**/api/v1/land/analyze', async route => {
    expect(route.request().postDataJSON()).toMatchObject({ input: '1111010100100010000', input_type: 'pnu' });
    await route.fulfill({ json: { pnu: { pnu: '1111010100100010000' }, zone_info: { zones: ['제2종일반주거지역'] },
      regulations: { bcr: { limit_pct: null }, far: { limit_pct: null } }, land_info: { land_area_m2: 123 },
      law_articles: null, errors: ['적용 조례 증거 부족'], restrictions: [], setback_lines: { datum_result: { elevation_m: null, elevation_source: 'failed', case: null, basis: 'elevation_fetch_failed' } } } });
  });
  await page.goto(process.env.EDITOR_TEST_URL + '/map');
  await expect(page.getByText('필지를 선택하세요')).toBeVisible();
  await expect(page.locator('.ol-viewport')).toBeVisible();
  await page.getByRole('textbox', { name: '주소 또는 PNU 검색' }).fill('1111010100100010000');
  await page.getByRole('button', { name: '검색', exact: true }).click();
  await expect(page.getByText('적용 조례 증거 부족', { exact: true })).toBeVisible();
  await expect(page.getByRole('alert').filter({ hasText: '필지 경계 공급자 미설정' })).toBeVisible();
  await expect(page.getByText('미확정', { exact: true })).toBeVisible();
  await expect(page.getByText('일부 결과 — 확인 필요')).toBeVisible();
  await expect(page.getByText('지반 레벨 (§119 datum)').locator('../..')).toHaveCSS('opacity', '1');
  await expect(page.getByRole('alert').filter({ hasText: '지도 또는 지적도를 불러오지 못했습니다.' })).toBeVisible();
  expect(errors).toEqual([]);
  await page.screenshot({ path: 'test-results/native-vworld-map.png', fullPage: true });
  await page.reload();
  await expect(page.getByText('필지를 선택하세요')).toBeVisible();
});
