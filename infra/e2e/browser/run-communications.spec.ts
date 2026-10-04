import {test,expect} from '@playwright/test';
const base={run_id:'r',request_id:'editor:b:k',owner_project_id:'p',branch_id:'main',goal:'health',
  status:'succeeded',receipt_task_ids:['health'],pending_input:false};
const communication={id:'health',task_id:'health',tool:'health',agent:'law',state:'finished',
  request_text:'{"tool":"health"}',response_text:'법규 에이전트 응답 <script>unsafe</script>',transport:'a2a',truncated:false};

test('saved agent request and reply remain visible after reload',async({page})=>{
  await page.route('**/api/v1/platform/runs/r?*',r=>r.fulfill({json:{...base,communications_available:true,
    communications_truncated:false,communications:[communication]}}));
  await page.goto('/runs/r?project_id=b');
  await expect(page.getByRole('heading',{name:'에이전트 대화 기록'})).toBeVisible();
  await page.getByText('요청 내용',{exact:true}).click();
  await expect(page.getByText(communication.request_text,{exact:true})).toBeVisible();
  await page.getByText('응답 내용',{exact:true}).click();
  await expect(page.getByText(communication.response_text,{exact:true})).toBeVisible();
  await expect(page.locator('.run-communications script')).toHaveCount(0);
  await page.reload();
  await expect(page.getByText('orchestrator → law',{exact:true})).toBeVisible();
});

test('old gateway shows unavailable rather than sample conversation',async({page})=>{
  await page.route('**/api/v1/platform/runs/r?*',r=>r.fulfill({json:base}));
  await page.goto('/runs/r?project_id=b');
  await expect(page.getByText('연결된 서비스가 대화 기록을 제공하지 않습니다.',{exact:true})).toBeVisible();
  await expect(page.locator('.run-communications article')).toHaveCount(0);
});

test('flow groups recorded agents and filters their actual calls',async({page})=>{
  const rows=[communication,{...communication,id:'law2',task_id:'law_review',state:'partial'},
    {...communication,id:'systems',agent:'systems',state:'failed'},
    {...communication,id:'unknown',agent:null}];
  await page.route('**/api/v1/platform/runs/r?*',r=>r.fulfill({json:{...base,
    communications_available:true,communications_truncated:false,communications:rows}}));
  await page.goto('/runs/r?project_id=b');
  await expect(page.getByRole('heading',{name:'기록된 협업 흐름'})).toBeVisible();
  await expect(page.getByText('수신 에이전트가 기록되지 않은 호출 1건',{exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:'law 호출 2건 보기'})).toBeVisible();
  await page.getByRole('button',{name:'law 호출 2건 보기'}).click();
  await expect(page.locator('.run-communications article')).toHaveCount(2);
  await expect(page.locator('.run-communications article').filter({hasText:'partial'})).toHaveCount(1);
  await page.getByRole('button',{name:'전체 호출 보기'}).click();
  await expect(page.locator('.run-communications article')).toHaveCount(4);
  await page.getByRole('button',{name:'systems 호출 1건 보기'}).click();
  await expect(page.locator('.run-communications article')).toHaveCount(1);
  await expect(page.locator('.run-communications article')).toContainText('failed');
});

test('missing identities do not fabricate topology edges',async({page})=>{
  await page.route('**/api/v1/platform/runs/r?*',r=>r.fulfill({json:{...base,
    communications_available:true,communications_truncated:false,communications:[{...communication,agent:null}]}}));
  await page.goto('/runs/r?project_id=b');
  await expect(page.getByText('연결 관계를 표시할 수신 에이전트 기록이 없습니다.',{exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:/호출 [0-9]+건 보기/})).toHaveCount(0);
  await expect(page.locator('.run-communications article')).toHaveCount(1);
});

test('response limit counts Unicode characters consistently with the owner',async({page})=>{
  await page.route('**/api/v1/platform/runs/r?*',r=>r.fulfill({json:{...base,communications_available:true,
    communications_truncated:false,communications:[{...communication,response_text:'😀'.repeat(8000),truncated:true}]}}));
  await page.goto('/runs/r?project_id=b');
  await expect(page.locator('.run-communications article')).toHaveCount(1);
  await expect(page.getByText('일부 내용이 생략되었습니다.',{exact:true})).toBeVisible();
});

test('saved A2A receipts travel through owner and Editor HTTP to the browser',async({page})=>{
  test.skip(!process.env.EDITOR_SAVED_RUN,'Requires isolated copy of saved owner and project databases');
  await page.goto(process.env.EDITOR_SAVED_RUN!);
  await expect(page.getByRole('heading',{name:'에이전트 대화 기록'})).toBeVisible();
  await expect(page.locator('.run-communications article')).toHaveCount(3);
  await expect(page.locator('.run-communications').getByText('A2A 응답 기록',{exact:false})).toHaveCount(3);
  await page.locator('.run-communications summary').filter({hasText:'응답 내용'}).first().click();
  await expect(page.locator('.run-communications pre:visible')).not.toBeEmpty();
  await page.reload();
  await expect(page.locator('.run-communications article')).toHaveCount(3);
  await page.screenshot({path:'test-results/editor-saved-a2a-communications.png',fullPage:true});
});

test('new A2A identities appear in the collaboration flow',async({page})=>{
  test.skip(!process.env.EDITOR_FLOW_RUN,'Requires a new isolated A2A health run');
  await page.goto(process.env.EDITOR_FLOW_RUN!);
  for(const agent of ['law','masterplan','elevation']){
    await page.getByRole('button',{name:`${agent} 호출 1건 보기`}).click();
    await expect(page.locator('.run-communications article')).toHaveCount(1);
    await expect(page.locator('.run-communications article')).toContainText(`orchestrator → ${agent}`);
  }
  await page.getByRole('button',{name:'전체 호출 보기'}).click();
  await expect(page.locator('.run-communications article')).toHaveCount(3);
  await page.reload();
  await expect(page.getByRole('button',{name:'law 호출 1건 보기'})).toBeVisible();
  await page.screenshot({path:'test-results/editor-live-communication-flow.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  expect(await page.locator('.communication-flow').evaluate(el=>el.scrollWidth<=el.clientWidth)).toBe(true);
});
