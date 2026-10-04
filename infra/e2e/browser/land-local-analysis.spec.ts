import {test,expect} from '@playwright/test';

test('stats scopes count only stored records and remain independent of analysis input',async ({page})=>{
  const requests:string[]=[];
  await page.route('**/api/v1/land/zones',r=>r.fulfill({json:{zones:[{zone_name:'제2종일반주거지역'}]}}));
  await page.route('**/api/v1/land/stats*',r=>{
    const scope=new URL(r.request().url()).searchParams.get('scope')!;
    requests.push(scope);
    return r.fulfill({json:{scope:scope==='editor'?'editor_local':`editor_${scope}`,
      total_queries:scope==='all'?9:scope==='imported'?6:3,error_count:0,avg_response_time_ms:2,by_input_type:[]}});
  });
  await page.goto('/land');
  await expect(page.getByLabel('통계 기록 범위')).toHaveValue('all');
  await expect(page.getByText('조회 9건 · 오류 0건 · 평균 2ms',{exact:true})).toBeVisible();
  await page.getByLabel('통계 기록 범위').selectOption('imported');
  await expect(page.getByText('조회 6건 · 오류 0건 · 평균 2ms',{exact:true})).toBeVisible();
  await expect(page.getByText('Editor로 실제 가져온 과거 기록만 포함합니다.',{exact:true})).toBeVisible();
  await page.getByLabel('입력 형식').selectOption('raw');
  await page.getByLabel('용도지역 직접 지정').selectOption('제2종일반주거지역');
  await page.getByLabel('법령 원문 검색').uncheck();
  await expect(page.getByLabel('통계 기록 범위')).toHaveValue('imported');
  await expect(page.getByText('조회 6건 · 오류 0건 · 평균 2ms',{exact:true})).toBeVisible();
  await page.getByLabel('통계 기록 범위').selectOption('editor');
  await expect(page.getByText('조회 3건 · 오류 0건 · 평균 2ms',{exact:true})).toBeVisible();
  await page.getByLabel('통계 기록 범위').selectOption('all');
  await expect(page.getByText('조회 9건 · 오류 0건 · 평균 2ms',{exact:true})).toBeVisible();
  expect(requests.every(scope=>['editor','imported','all'].includes(scope))).toBe(true);
});

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
  await page.getByLabel('통계 기록 범위').selectOption('editor');
  await page.getByLabel('법령 원문 검색').uncheck();
  await statsResponse;
  await page.locator('form').getByRole('button',{name:'대지 분석',exact:true}).click();
  await expect(page.getByText('분석 결과를 저장했습니다.',{exact:true})).toBeVisible();
  await expect(page.getByRole('heading',{name:'대지 분석 통계'})).toBeVisible();
  await expect(page.getByText('Editor에서 새로 저장한 분석 기록입니다.',{exact:true})).toBeVisible();
  await expect(page.getByText('허가 적합성은 검증되지 않았습니다.',{exact:true})).toBeVisible();
});

test('switching scope suppresses a delayed all-record stats response',async ({page})=>{
  let release!:()=>void;
  const delayed=new Promise<void>(resolve=>{release=resolve;});
  let started!:()=>void;
  const pending=new Promise<void>(resolve=>{started=resolve;});
  let finished!:()=>void;
  const completed=new Promise<void>(resolve=>{finished=resolve;});
  await page.route('**/api/v1/land/zones',r=>r.fulfill({json:{zones:[]}}));
  await page.route('**/api/v1/land/stats*',async r=>{
    const local=r.request().url().includes('scope=editor');
    if(!local){started();await delayed;}
    await r.fulfill({json:{total_queries:local?7:999,error_count:0,avg_response_time_ms:1,by_input_type:[]}}).catch(()=>{});
    if(!local)finished();
  });
  await page.goto('/land');await pending;
  await page.getByLabel('통계 기록 범위').selectOption('editor');
  await page.getByLabel('입력 형식').selectOption('raw');
  await page.getByLabel('법령 원문 검색').uncheck();
  await expect(page.getByText('조회 7건 · 오류 0건 · 평균 1ms',{exact:true})).toBeVisible();
  release();
  await completed;
  await expect(page.getByLabel('통계 기록 범위')).toHaveValue('editor');
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

test('isolated imported history remains separate when Editor saves a new analysis',async ({page,request})=>{
  test.skip(!process.env.EDITOR_HISTORY_ANALYSIS,'Requires isolated Editor with imported analysis history');
  const stats=async (scope:string)=>{
    const response=await request.get(`/api/v1/land/stats?scope=${scope}`);
    expect(response.ok()).toBeTruthy();return response.json();
  };
  const imported=await stats('imported');const editor=await stats('editor');const all=await stats('all');
  expect(imported.scope).toBe('editor_imported');expect(imported.total_queries).toBeGreaterThan(0);
  expect(editor.scope).toBe('editor_local');expect(all.scope).toBe('editor_all');
  expect(all.total_queries).toBe(editor.total_queries+imported.total_queries);
  await page.goto('/land');
  await page.getByLabel('통계 기록 범위').selectOption('imported');
  await expect(page.getByText(new RegExp(`조회 ${imported.total_queries}건 ·`))).toBeVisible();
  await page.getByLabel('입력 형식').selectOption('raw');
  await page.getByLabel('용도지역 직접 지정').selectOption({index:1});
  await page.getByLabel('법령 원문 검색').uncheck();
  await page.locator('form').getByRole('button',{name:'대지 분석',exact:true}).click();
  await expect(page.getByText('분석 결과를 저장했습니다.',{exact:true})).toBeVisible();
  await expect(page.getByLabel('통계 기록 범위')).toHaveValue('imported');
  await expect(page.getByText(new RegExp(`조회 ${imported.total_queries}건 ·`))).toBeVisible();
  expect((await stats('imported')).total_queries).toBe(imported.total_queries);
  expect((await stats('editor')).total_queries).toBe(editor.total_queries+1);
  const updated=await stats('all');expect(updated.total_queries).toBe(all.total_queries+1);
  await page.getByLabel('통계 기록 범위').selectOption('all');
  await expect(page.getByText(new RegExp(`조회 ${updated.total_queries}건 ·`))).toBeVisible();
  await page.screenshot({path:'test-results/editor-imported-history.png',fullPage:true});
});
