import { after as afterAll, before as beforeAll, beforeEach, afterEach, test } from 'node:test';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { chromium, expect, type Browser, type Page } from '@playwright/test';
import type {} from './use-design-job.browser-fixture';

let browser: Browser;
let page: Page;
let script: string;
beforeAll(async () => {
  script = execFileSync(process.env.BUN_EXECUTABLE || 'bun', ['build', fileURLToPath(new URL('./use-design-job.browser-fixture.tsx', import.meta.url)),
    '--target=browser', '--format=iife', '--define', 'process.env.NODE_ENV="development"',
    '--define', 'process.env.NEXT_PUBLIC_BASE_PATH=""'], { encoding:'utf8', maxBuffer: 5_000_000 });
  browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_BROWSER_CHANNEL });
});
beforeEach(async () => {
  page = await browser.newPage();
  await page.setContent('<div id="root"></div>');
  await page.addScriptTag({ content: script });
});
afterEach(async () => { await page?.close(); });
afterAll(async () => { await browser?.close(); });

const boundary = (pnu: string) => {
  const x = 127 + pnu.charCodeAt(0) / 1000;
  return { pnu, geometry: { type: 'Polygon', coordinates: [[[x,37],[x+.01,37],[x,37.01],[x,37]]] }, area_m2: 100 };
};
const law = (bcr: number) => ({ regulations: { bcr: { limit_pct: bcr } }, zone_info: { zones: ['zone-'+bcr] } });
async function start(key: string, action: 'loadSiteBoundary' | 'loadConstraints' | 'startJob', params: unknown) {
  await page.evaluate(({key,action,params}) => window.designJobHarness.start(key,action,params), {key,action,params});
}
async function settle(index: number, value: unknown, key: string, status = 200) {
  return page.evaluate(({index,value,key,status}) => window.designJobHarness.settle(index,value,key,status), {index,value,key,status});
}
async function ready() {
  await start('boundary', 'loadSiteBoundary', 'A');
  await settle(0, boundary('A'), 'boundary');
  await start('law', 'loadConstraints', {pnu:'A'});
  await settle(1, law(60), 'law');
}
const state = () => page.evaluate(() => window.designJobHarness.state());

test('new boundary clears old runnable context even when lookup fails', async () => {
  await ready();
  await start('next', 'loadSiteBoundary', 'B');
  expect((await state()).sitePolygon).toBeNull();
  expect((await state()).constraints).toEqual([]);
  await settle(2, {error:'missing parcel'}, 'next', 404);
  expect((await state()).sitePolygon).toBeNull();
  await start('job', 'startJob', {pnu:'B'});
  expect(await page.evaluate(() => window.designJobHarness.result('job'))).toBeNull();
  expect(await page.evaluate(() => window.designJobHarness.requests().length)).toBe(3);
});

test('late boundary success and failure return null and cannot overwrite newer parcel', async () => {
  await start('a','loadSiteBoundary','A');
  await start('b','loadSiteBoundary','B');
  await settle(1,boundary('B'),'b');
  expect(await settle(0,boundary('A'),'a')).toBeNull();
  expect(await page.evaluate(() => window.designJobHarness.requests()[0].aborted)).toBe(true);
  await start('c','loadSiteBoundary','C');
  await start('d','loadSiteBoundary','D');
  await settle(3,boundary('D'),'d');
  expect(await settle(2,{error:'late error'},'c',500)).toBeNull();
  expect((await state()).error).toBeNull();
  expect((await state()).sitePolygon).toEqual(boundary('D').geometry);
});

test('constraint requests are latest-only across building types and parcels', async () => {
  await ready();
  await start('oldlaw','loadConstraints',{pnu:'A',building_type:'old'});
  await start('newlaw','loadConstraints',{pnu:'A',building_type:'new'});
  expect((await state()).constraints).toEqual([]);
  await settle(3,law(40),'newlaw');
  expect(await settle(2,law(80),'oldlaw')).toBeNull();
  expect((await state()).constraints[0].val).toBe(40);
  await start('pendinglaw','loadConstraints',{pnu:'A'});
  await start('b','loadSiteBoundary','B');
  expect(await settle(4,{error:'late law'},'pendinglaw',500)).toBeNull();
  expect((await state()).loading).toBe(true);
  await settle(5,boundary('B'),'b');
  await start('wronglaw','loadConstraints',{pnu:'A'});
  expect(await page.evaluate(() => window.designJobHarness.result('wronglaw'))).toBeNull();
  expect((await state()).constraints).toEqual([]);
});

for (const invalidation of ['parcel','constraints','reset','unmount'] as const) {
  test(`pending job cannot reconnect after ${invalidation}`, async () => {
    await ready();
    await start('job','startJob',{pnu:'A'});
    if (invalidation === 'parcel') await start('b','loadSiteBoundary','B');
    if (invalidation === 'constraints') await start('newlaw','loadConstraints',{pnu:'A',building_type:'changed'});
    if (invalidation === 'reset') await page.evaluate(() => window.designJobHarness.reset());
    if (invalidation === 'unmount') await page.evaluate(() => window.designJobHarness.unmount());
    expect(await settle(2,{id:'old-job',pnu:'A'},'job')).toBeNull();
    expect(await page.evaluate(() => window.designJobHarness.requests()[2].aborted)).toBe(true);
    expect((await state()).job).toBeNull();
  });
}

test('current context can create a job and stale PNU cannot', async () => {
  await ready();
  await start('wrong','startJob',{pnu:'B'});
  expect(await page.evaluate(() => window.designJobHarness.result('wrong'))).toBeNull();
  await start('job','startJob',{pnu:'A'});
  expect(await settle(2,{id:'current-job',pnu:'A'},'job')).toEqual({id:'current-job',pnu:'A'});
  expect((await state()).job?.id).toBe('current-job');
});

test('same-tick parcel switch cannot submit geometry from the previous render', async () => {
  await ready();
  await page.evaluate(() => {
    window.designJobHarness.start('b','loadSiteBoundary','B');
    window.designJobHarness.start('job','startJob',{pnu:'A'});
  });
  expect(await page.evaluate(() => window.designJobHarness.result('job'))).toBeNull();
  expect(await page.evaluate(() => window.designJobHarness.requests().length)).toBe(3);
});

test('late failed job cannot clear new parcel loading or show stale errors', async () => {
  await ready();
  await start('job','startJob',{pnu:'A'});
  await start('b','loadSiteBoundary','B');
  expect(await settle(2,{error:'old job failed'},'job',500)).toBeNull();
  expect((await state()).error).toBeNull();
  expect((await state()).loading).toBe(true);
  expect((await state()).sitePolygon).toBeNull();
});

test('resolved address adopts returned PNU and reset invalidates boundary response', async () => {
  await start('address','loadSiteBoundary','address query');
  await settle(0,boundary('A'),'address');
  await start('law','loadConstraints',{pnu:'A'});
  await settle(1,law(50),'law');
  expect((await state()).constraints[0].val).toBe(50);
  await start('b','loadSiteBoundary','B');
  await page.evaluate(() => window.designJobHarness.reset());
  expect(await settle(2,boundary('B'),'b')).toBeNull();
  expect((await state()).sitePolygon).toBeNull();
  expect((await state()).loading).toBe(false);
});
