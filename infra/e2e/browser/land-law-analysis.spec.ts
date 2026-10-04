import {test,expect} from '@playwright/test';

for(const available of [true,false]){
  test(`advisory ${available?'proposal is escaped and separate':'unavailable is explicit'}`,async ({page})=>{
    const hostile='<img src=x onerror="window.advisoryExecuted=true">';
    await page.route('**/api/v1/land/zones',r=>r.fulfill({json:{zones:[{zone_name:'zone'}]}}));
    await page.route('**/api/v1/land/stats*',r=>r.fulfill({json:{total_queries:1,error_count:0,avg_response_time_ms:1,by_input_type:[]}}));
    await page.route('**/api/v1/land/analyze',r=>r.fulfill({json:{execution_owner:'editor',pnu:null,land_info:null,
      zone_info:null,law_articles:null,regulations:{adjacent_setback:{min_m:0.5}},restrictions:[],
      advisory:{status:available?'unverified_proposal':'unavailable',proposals:available?{
        adjacent_setback:{adjacent_setback_m:999,notes:hostile}}:{}}}}));
    await page.goto('/land');await page.getByLabel('입력 형식').selectOption('raw');
    await page.getByLabel('용도지역 직접 지정').selectOption('zone');
    await page.locator('form').getByRole('button',{name:'대지 분석',exact:true}).click();
    const advisory=page.getByRole('region',{name:'검토용 추출 제안'});
    await expect(advisory).toBeVisible();
    await expect(advisory).toContainText('계산값에 반영되지 않습니다.');
    if(available){
      await expect(advisory).toContainText('미검증 제안');
      await expect(advisory).toContainText(hostile);
      await expect(advisory.locator('img')).toHaveCount(0);
      expect(await page.evaluate(()=>('advisoryExecuted' in window))).toBe(false);
    }else await expect(advisory).toContainText('추출 제안을 제공할 수 없습니다.');
    const rule=page.locator('article').filter({has:page.getByRole('heading',{name:'인접 대지 이격',exact:true})}).first();
    await expect(rule).toContainText('0.5');await expect(rule).not.toContainText('999');
  });
}

test('isolated law search and advisory keep deduplicated evidence separate from calculations',async ({page})=>{
  test.skip(!process.env.EDITOR_LAW_ANALYSIS,'Requires Editor law transport and optional extraction fixtures');
  await page.goto('/land');await page.getByLabel('입력 형식').selectOption('raw');
  await page.getByLabel('용도지역 직접 지정').selectOption({index:1});
  await expect(page.getByLabel('법령 원문 검색')).toBeChecked();
  const pending=page.waitForResponse(r=>r.url().endsWith('/api/v1/land/analyze'));
  await page.locator('form').getByRole('button',{name:'대지 분석',exact:true}).click();
  const response=await pending;expect(response.ok()).toBeTruthy();const value=await response.json();
  expect(value.execution_owner).toBe('editor');expect(value.storage.saved).toBe(true);
  expect(value.law_articles.total_count).toBe(1);expect(value.law_articles.articles).toHaveLength(1);
  expect(value.advisory.status).toBe('unverified_proposal');
  expect(value.advisory.proposals.adjacent_setback.adjacent_setback_m).toBe(999);
  expect(value.regulations.adjacent_setback.min_m).not.toBe(999);
  await expect(page.getByText(process.env.EDITOR_LAW_ARTICLE_TEXT||'fixture law evidence',{exact:true})).toBeVisible();
  await expect(page.getByRole('region',{name:'검토용 추출 제안'})).toContainText('미검증 제안');
  await expect(page.getByText('분석 결과를 저장했습니다.',{exact:true})).toBeVisible();
});
