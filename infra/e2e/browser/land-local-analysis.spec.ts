import {test,expect} from '@playwright/test';

test('raw zones submit without address and show saved local scope',async ({page})=>{
  await page.route('**/api/v1/land/zones',r=>r.fulfill({json:{zones:[{zone_name:'제2종일반주거지역'}]}}));
  await page.route('**/api/v1/land/stats*',r=>r.fulfill({json:{total_queries:3,error_count:0,avg_response_time_ms:2,by_input_type:[]}}));
  await page.route('**/api/v1/land/analyze',r=>{
    expect(r.request().postDataJSON()).toEqual({input:'',input_type:'raw',zones:['제2종일반주거지역'],include_law:false});
    return r.fulfill({json:{pnu:null,land_info:null,zone_info:null,regulations:null,law_articles:null,restrictions:[],
      storage:{saved:true,analysis_id:'local-1'},
      assessment:{status:'needs_evidence',permit_compliance_verified:false,missing_evidence:[]}}});
  });
  await page.goto('/land');
  await page.getByLabel('입력 형식').selectOption('raw');
  await expect(page.getByLabel('주소 또는 PNU')).toHaveCount(0);
  await expect(page.getByRole('button',{name:'주소/PNU 확인',exact:true})).toHaveCount(0);
  await expect(page.getByRole('heading',{name:'필지 경계 조회'})).toHaveCount(0);
  await expect(page.locator('form').getByRole('button',{name:'대지 분석',exact:true})).toBeDisabled();
  await page.getByLabel('용도지역 직접 지정').selectOption('제2종일반주거지역');
  const statsResponse=page.waitForResponse(r=>r.url().endsWith('/stats?scope=editor'));
  await page.getByLabel('법령 원문 검색').uncheck();
  await statsResponse;
  await page.locator('form').getByRole('button',{name:'대지 분석',exact:true}).click();
  await expect(page.getByText('분석 결과를 저장했습니다.',{exact:true})).toBeVisible();
  await expect(page.getByRole('heading',{name:'Editor 저장 분석 통계'})).toBeVisible();
  await expect(page.getByText('기존 서비스의 과거 분석 기록은 포함하지 않습니다.',{exact:true})).toBeVisible();
  await expect(page.getByText('허가 적합성은 검증되지 않았습니다.',{exact:true})).toBeVisible();
});

test('switching scope suppresses a delayed legacy stats response',async ({page})=>{
  let release!:()=>void;
  const delayed=new Promise<void>(resolve=>{release=resolve;});
  let started!:()=>void;
  const pending=new Promise<void>(resolve=>{started=resolve;});
  await page.route('**/api/v1/land/zones',r=>r.fulfill({json:{zones:[]}}));
  await page.route('**/api/v1/land/stats*',async r=>{
    const local=r.request().url().includes('scope=editor');
    if(!local){started();await delayed;}
    await r.fulfill({json:{total_queries:local?7:999,error_count:0,avg_response_time_ms:1,by_input_type:[]}}).catch(()=>{});
  });
  await page.goto('/land');await pending;
  await page.getByLabel('입력 형식').selectOption('raw');
  await page.getByLabel('법령 원문 검색').uncheck();
  await expect(page.getByText('조회 7건 · 오류 0건 · 평균 1ms',{exact:true})).toBeVisible();
  release();
  await expect(page.getByRole('heading',{name:'ARR 분석 통계'})).toHaveCount(0);
  await expect(page.getByText(/조회 999건/)).toHaveCount(0);
});

test('isolated Editor saves real raw analysis and counts it locally',async ({page,request})=>{
  test.skip(!process.env.EDITOR_LOCAL_ANALYSIS,'Requires isolated Editor backend with local analysis repository');
  const before=await request.get('/api/v1/land/stats?scope=editor');
  expect(before.ok()).toBeTruthy();
  const oldStats=await before.json();
  await page.goto('/land');
  await page.getByLabel('입력 형식').selectOption('raw');
  await page.getByLabel('용도지역 직접 지정').selectOption({index:1});
  await page.getByLabel('법령 원문 검색').uncheck();
  const analysis=page.waitForResponse(r=>r.url().endsWith('/api/v1/land/analyze'));
  await page.locator('form').getByRole('button',{name:'대지 분석',exact:true}).click();
  const response=await analysis;
  expect(response.ok()).toBeTruthy();
  const result=await response.json();
  expect(result.assessment.permit_compliance_verified).toBe(false);
  expect(result.storage.saved).toBe(true);
  expect(result.regulations.bcr.limit_pct).toBeNull();
  expect(typeof result.regulations.bcr.national_ceiling_pct).toBe('number');
  await expect(page.getByText('분석 결과를 저장했습니다.',{exact:true})).toBeVisible();
  const after=await request.get('/api/v1/land/stats?scope=editor');
  expect((await after.json()).total_queries).toBe(oldStats.total_queries+1);
});
