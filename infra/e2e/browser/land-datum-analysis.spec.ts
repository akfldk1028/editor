import {test,expect} from '@playwright/test';

for(const failed of [false,true]){
  test(`datum ${failed?'failure does not invent zero elevation':'height shows source and basis'}`,async({page})=>{
    await page.route('**/api/v1/land/zones',r=>r.fulfill({json:{zones:[{zone_name:'zone'}]}}));
    await page.route('**/api/v1/land/stats*',r=>r.fulfill({json:{total_queries:1,error_count:0,avg_response_time_ms:1,by_input_type:[]}}));
    await page.route('**/api/v1/land/analyze',r=>r.fulfill({json:{pnu:null,land_info:null,zone_info:null,
      regulations:null,law_articles:null,restrictions:[],setback_lines:{datum_result:{
        elevation_m:failed?null:12.5,elevation_source:failed?'failed':'open_meteo',basis:failed?'elevation_fetch_failed':'ground_flat',
        provenance:{actual_provider:failed?null:'open_meteo',fallback_used:!failed},notes:['<b>provider note</b>']}}}}));
    await page.goto('/land');await page.getByLabel('입력 형식').selectOption('raw');
    await page.getByLabel('용도지역 직접 지정').selectOption('zone');
    await page.locator('form').getByRole('button',{name:'대지 분석',exact:true}).click();
    const datum=page.getByRole('region',{name:'기준 지반고'});
    await expect(datum).toBeVisible();await expect(datum).toContainText('<b>provider note</b>');
    await expect(datum.locator('b')).toHaveCount(0);
    if(failed){await expect(datum).toContainText('미확인 절대고도');await expect(datum).not.toContainText('0 m');}
    else{await expect(datum).toContainText('12.5 m');await expect(datum).toContainText('open_meteo');
      await expect(datum).toContainText('평탄 대지');await expect(datum).toContainText('대체 고도 자료');}
  });
}

test('isolated Editor datum HTTP success and failure remain distinct',async({page})=>{
  test.skip(!process.env.EDITOR_DATUM_ANALYSIS,'Requires isolated datum HTTP fixture');
  await page.goto('/land');await page.getByLabel('법령 원문 검색').uncheck();
  for(const failed of [false,true]){
    await page.getByLabel('주소 또는 PNU').fill(failed?'1168011200101280004':'1168011200101280003');
    const pending=page.waitForResponse(r=>r.url().endsWith('/api/v1/land/analyze'));
    await page.locator('form').getByRole('button',{name:'대지 분석',exact:true}).click();
    const response=await pending;expect(response.ok()).toBeTruthy();const value=await response.json();
    expect(value.execution_owner).toBe('editor');expect(value.storage.saved).toBe(true);
    const datum=value.setback_lines.datum_result;
    const region=page.getByRole('region',{name:'기준 지반고'});
    if(failed){expect(datum.elevation_m).toBeNull();expect(datum.elevation_source).toBe('failed');
      await expect(region).toContainText('미확인 절대고도');await expect(region).not.toContainText('0 m');}
    else{expect(datum.elevation_m).toBeCloseTo(12.5);expect(datum.provenance.actual_provider).toBe('open_meteo');
      await expect(region).toContainText('12.5 m');await expect(region).toContainText('open_meteo');}
  }
});
