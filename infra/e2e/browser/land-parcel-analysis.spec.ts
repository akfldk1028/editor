import {test,expect} from '@playwright/test';

test('successful cached PNU result preserves the selected stats scope',async ({page})=>{
  await page.route('**/api/v1/land/zones',r=>r.fulfill({json:{zones:[]}}));
  await page.route('**/api/v1/land/stats*',r=>r.fulfill({json:{total_queries:1,error_count:0,avg_response_time_ms:1,by_input_type:[]}}));
  await page.route('**/api/v1/land/analyze',r=>r.fulfill({json:{execution_owner:'editor',storage:{saved:true},
    pnu:null,land_info:{success:true,cache:{stale:true,fetched_at:'2026-10-03T10:00:00+00:00',saved:true}},
    regulations:null,zone_info:null,law_articles:null,restrictions:[]}}));
  await page.goto('/land');await page.getByLabel('통계 기록 범위').selectOption('imported');
  await page.getByLabel('주소 또는 PNU').fill('1168011200101280003');
  await page.getByLabel('법령 원문 검색').uncheck();
  await page.locator('form').getByRole('button',{name:'대지 분석',exact:true}).click();
  await expect(page.getByRole('heading',{name:'대지 분석 통계'})).toBeVisible();
  await expect(page.getByRole('alert')).toContainText('이전에 저장한 토지 정보를 사용했습니다.');
  await expect(page.getByRole('alert')).toContainText('2026-10-03T10:00:00+00:00');
  await expect(page.getByText('분석 결과를 저장했습니다.',{exact:true})).toBeVisible();
  await expect(page.locator('form').getByRole('button',{name:'대지 분석',exact:true})).toBeEnabled();
  await page.getByLabel('주소 또는 PNU').fill('1168011200101280004');
  await expect(page.getByRole('heading',{name:'대지 분석 통계'})).toBeVisible();
  await expect(page.getByRole('alert')).toHaveCount(0);
  await expect(page.getByLabel('통계 기록 범위')).toHaveValue('imported');
});

for(const kind of ['pnu','address'] as const){
  test(`isolated ${kind} analysis uses provider fixtures and keeps geometry`,async ({page})=>{
    test.skip(!process.env.EDITOR_PARCEL_ANALYSIS,'Requires isolated Editor with Vworld transport fixtures');
    await page.goto('/land');
    await page.getByLabel('주소 또는 PNU').fill(kind==='pnu'?(process.env.EDITOR_PARCEL_PNU||'1168011200101280003'):
      (process.env.EDITOR_PARCEL_ADDRESS||'fixture address'));
    await page.getByLabel('법령 원문 검색').uncheck();
    const pending=page.waitForResponse(r=>r.url().endsWith('/api/v1/land/analyze'));
    await page.locator('form').getByRole('button',{name:'대지 분석',exact:true}).click();
    const response=await pending;expect(response.ok()).toBeTruthy();const value=await response.json();
    expect(value.execution_owner).toBe('editor');expect(value.storage.saved).toBe(true);
    expect(value.setback_lines.buildable_area).toBeTruthy();
    expect(value.assessment.permit_compliance_verified).toBe(false);
    await expect(page.getByRole('heading',{name:'대지 분석 통계'})).toBeVisible();
    await expect(page.getByText('분석 결과를 저장했습니다.',{exact:true})).toBeVisible();
  });
}

test('isolated failed live lookup displays persisted cache timestamp',async ({page})=>{
  test.skip(!process.env.EDITOR_PARCEL_ANALYSIS,'Requires preseeded cached PNU and failed NED provider fixtures');
  await page.goto('/land');
  await page.getByLabel('주소 또는 PNU').fill(process.env.EDITOR_PARCEL_CACHED_PNU||'1168011200101280004');
  await page.getByLabel('법령 원문 검색').uncheck();
  const pending=page.waitForResponse(r=>r.url().endsWith('/api/v1/land/analyze'));
  await page.locator('form').getByRole('button',{name:'대지 분석',exact:true}).click();
  const response=await pending;expect(response.ok()).toBeTruthy();const value=await response.json();
  expect(value.land_info.success).toBe(true);expect(value.land_info.cache.stale).toBe(true);
  expect(value.land_info.cache.fetched_at).toBeTruthy();
  await expect(page.getByRole('alert').filter({hasText:'이전에 저장한 토지 정보를 사용했습니다.'}))
    .toContainText(value.land_info.cache.fetched_at);
});
