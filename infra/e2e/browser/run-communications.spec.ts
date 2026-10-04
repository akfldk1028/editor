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
