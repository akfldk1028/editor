import { after, before, beforeEach, afterEach, test } from 'node:test';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { chromium, expect, type Browser, type Page } from '@playwright/test';
import type {} from './use-interactive-agent-review.browser-fixture';

let browser:Browser;
let page:Page;
let script:string;
before(async()=>{
  script=execFileSync(process.env.BUN_EXECUTABLE || 'bun',['build',fileURLToPath(new URL('./use-interactive-agent-review.browser-fixture.tsx',import.meta.url)),
    '--target=browser','--format=iife','--define','process.env.NODE_ENV="development"',
    '--define','process.env.NEXT_PUBLIC_BASE_PATH=""'],{encoding:'utf8',maxBuffer:5_000_000});
  browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_BROWSER_CHANNEL});
});
beforeEach(async()=>{page=await browser.newPage();await page.setContent('<div id="root"></div>');await page.addScriptTag({content:script});});
afterEach(async()=>{await page?.close();});
after(async()=>{await browser?.close();});

for (const change of ['job','uid','unmount'] as const) {
  test(`late evidence after ${change} change cannot send handoffs or restore reviews`,async()=>{
    await page.evaluate(()=>window.agentReviewHarness.run('old'));
    await page.evaluate(change=>{
      if(change==='unmount') window.agentReviewHarness.unmount();
      else window.agentReviewHarness.setContext(change==='job'?'job-B':'job-A',change==='uid'?'uid-B':'uid-A');
    },change);
    await page.evaluate(()=>window.agentReviewHarness.settle(0,{final_status:'pass'},'old'));
    expect(await page.evaluate(()=>window.agentReviewHarness.sends())).toEqual([]);
    expect((await page.evaluate(()=>window.agentReviewHarness.state())).reviews).toEqual([]);
  });
}
test('late failed evidence does not repopulate fallback reviews or reset newer loading',async()=>{
  await page.evaluate(()=>window.agentReviewHarness.run('old'));
  await page.evaluate(()=>window.agentReviewHarness.setContext('job-B','uid-A'));
  await page.evaluate(()=>window.agentReviewHarness.run('new'));
  await page.evaluate(()=>window.agentReviewHarness.settle(0,{error:'old failure'},'old',500));
  const state=await page.evaluate(()=>window.agentReviewHarness.state());
  expect(state.reviews).toEqual([]);
  expect(state.error).toBe('');
  expect(state.loading).toBe(true);
});
test('switch during first handoff stops remaining handoffs and stale state writes',async()=>{
  await page.evaluate(()=>{window.agentReviewHarness.deferSend();window.agentReviewHarness.run('old');});
  await page.evaluate(()=>window.agentReviewHarness.resolveEvidence(0,{final_status:'pass'}));
  await page.waitForFunction(()=>window.agentReviewHarness.sends().length===1);
  await page.evaluate(()=>window.agentReviewHarness.setContext('job-B','uid-A'));
  await page.evaluate(()=>window.agentReviewHarness.resolveSend(0,'old'));
  expect((await page.evaluate(()=>window.agentReviewHarness.sends())).length).toBe(1);
  expect((await page.evaluate(()=>window.agentReviewHarness.state())).reviews).toEqual([]);
});
test('new review supersedes older review within the same selected design',async()=>{
  await page.evaluate(()=>{window.agentReviewHarness.run('old');window.agentReviewHarness.run('new');});
  await page.evaluate(()=>window.agentReviewHarness.settle(1,{final_status:'pass'},'new'));
  const current=await page.evaluate(()=>window.agentReviewHarness.state());
  const count=await page.evaluate(()=>window.agentReviewHarness.sends().length);
  expect(count).toBeGreaterThan(0);
  await page.evaluate(()=>window.agentReviewHarness.settle(0,{error:'old failure'},'old',500));
  expect(await page.evaluate(()=>window.agentReviewHarness.state())).toEqual(current);
  expect(await page.evaluate(()=>window.agentReviewHarness.sends().length)).toBe(count);
});
test('current evidence id zero still produces reviews and current failure still exposes fallback',async()=>{
  await page.evaluate(()=>window.agentReviewHarness.run('good'));
  expect(await page.evaluate(()=>window.agentReviewHarness.evidenceUrls()[0])).toContain('/results/0/evidence/');
  await page.evaluate(()=>window.agentReviewHarness.settle(0,{final_status:'pass'},'good'));
  expect((await page.evaluate(()=>window.agentReviewHarness.sends()))[0]).toMatchObject({metadata:{job_id:'job-A',design_id:0,design_uid:'uid-A'}});
  expect((await page.evaluate(()=>window.agentReviewHarness.state())).reviews.length).toBeGreaterThan(0);
  await page.evaluate(()=>window.agentReviewHarness.run('failed'));
  await page.evaluate(()=>window.agentReviewHarness.settle(1,{error:'current failure'},'failed',500));
  const state=await page.evaluate(()=>window.agentReviewHarness.state());
  expect(state.reviews.length).toBeGreaterThan(0);
  expect(state.error).toBe('current failure');
  expect(state.loading).toBe(false);
});

test('late direct message completion does not refresh the replacement job context',async()=>{
  await page.evaluate(()=>{window.agentReviewHarness.deferSend();window.agentReviewHarness.direct('old');});
  await page.waitForFunction(()=>window.agentReviewHarness.sends().length===1);
  await page.evaluate(()=>window.agentReviewHarness.setContext('job-B','uid-A'));
  const count=await page.evaluate(()=>window.agentReviewHarness.healthRequests());
  await page.evaluate(()=>window.agentReviewHarness.resolveSend(0,'old'));
  expect(await page.evaluate(()=>window.agentReviewHarness.healthRequests())).toBe(count);
});
