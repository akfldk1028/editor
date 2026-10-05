const { test, expect } = require('@playwright/test');
const { execFileSync } = require('node:child_process');
const { mkdtempSync, readFileSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const path = require('node:path');
let directory;
let script;
test.beforeAll(() => {
  directory = mkdtempSync(path.join(tmpdir(), 'editor-floor-hook-'));
  const bundle = path.join(directory, 'harness.js');
  const bun = process.env.BUN_BINARY || (process.platform === 'win32' ? path.join(process.env.APPDATA, 'npm/node_modules/bun/bin/bun.exe') : 'bun');
  execFileSync(bun, ['build', path.join(__dirname, 'floor-plan-hook-harness.tsx'), '--target', 'browser', '--outfile', bundle, '--define', 'process.env.NODE_ENV="development"'], { stdio: 'pipe' });
  script = readFileSync(bundle, 'utf8');
});
test.afterAll(() => {
  if (directory && path.dirname(path.resolve(directory)) === path.resolve(tmpdir()) && path.basename(directory).startsWith('editor-floor-hook-')) {
    rmSync(directory, { recursive: true, force: true });
  }
});

async function mount(page) {
  await page.setContent('<div id="root"></div>');
  await page.evaluate(() => {
    window.process = { env: { NODE_ENV: 'development', NEXT_PUBLIC_BASE_PATH: '' } };
    window.requests = [];
    window.fetch = (_url, init) => new Promise((resolve, reject) => {
      window.requests.push({ init, reject, resolve: value => resolve({ ok: true, json: async () => value }) });
    });
  });
  await page.addScriptTag({ content: script });
  await expect(page.locator('#state')).toContainText('"loading":false');
}
const state = async page => JSON.parse(await page.locator('#state').textContent());
const run = (page, id) => page.evaluate(id => window.floorHarness.run(id), id);
const settle = (page, index, result) => page.evaluate(({ index, result }) => window.requests[index].resolve(result), { index, result });

test('reset ignores a response arriving after parcel reset and aborts old work', async ({ page }) => {
  await mount(page);
  await run(page, 1);
  await page.evaluate(() => window.floorHarness.reset());
  await settle(page, 0, { design_id: 'old-parcel' });
  await expect.poll(() => state(page)).toEqual({ result: null, loading: false, tab: 'mass', error: null });
  expect(await page.evaluate(() => window.requests[0].init.signal?.aborted)).toBe(true);
});

test('new request owns result error and loading even when an older request settles later', async ({ page }) => {
  await mount(page);
  await run(page, 1);
  await run(page, 2);
  await settle(page, 0, { design_id: 'old' });
  await expect.poll(() => state(page)).toEqual({ result: null, loading: true, tab: 'mass', error: null });
  await settle(page, 1, { design_id: 'new' });
  await expect.poll(() => state(page)).toEqual({ result: { design_id: 'new' }, loading: false, tab: 'floor', error: null });
  await run(page, 3);
  await run(page, 4);
  await page.evaluate(() => window.requests[2].reject(new Error('stale error')));
  await expect.poll(async () => (await state(page)).error).toBe(null);
  expect((await state(page)).loading).toBe(true);
});

test('selection invalidates old response before debounce and unmount aborts work', async ({ page }) => {
  await mount(page);
  await run(page, 1);
  await page.evaluate(() => window.floorHarness.select(2));
  await settle(page, 0, { design_id: 'old-selection' });
  await expect.poll(async () => (await state(page)).result).toBe(null);
  await expect.poll(() => page.evaluate(() => window.requests.length)).toBe(2);
  await page.evaluate(() => window.floorHarness.unmount());
  expect(await page.evaluate(() => window.requests[1].init.signal?.aborted)).toBe(true);
  await settle(page, 1, { design_id: 'unmounted' });
  await expect(page.locator('#state')).toHaveCount(0);
});


test('manual generation cancels pending debounce and quick generation keeps the mass tab', async ({ page }) => {
  await mount(page);
  await page.evaluate(() => { window.floorHarness.select(1); window.floorHarness.run(1); });
  await page.waitForTimeout(300);
  expect(await page.evaluate(() => window.requests.length)).toBe(1);
  await settle(page, 0, { design_id: 'manual' });
  await expect.poll(async () => (await state(page)).tab).toBe('floor');
  await page.evaluate(() => window.floorHarness.reset());
  await page.evaluate(() => window.floorHarness.select(2));
  await expect.poll(() => page.evaluate(() => window.requests.length)).toBe(2);
  await settle(page, 1, { design_id: 'quick' });
  await expect.poll(() => state(page)).toEqual({ result: { design_id: 'quick' }, loading: false, tab: 'mass', error: null });
  const body = await page.evaluate(() => JSON.parse(window.requests[1].init.body));
  expect(body.algorithm).toBe('ga');
  expect(body.coordinate_frame).toBe('wgs84');
  expect(body.options).toEqual({ num_generations: 10, population_size: 15 });
});


test('turning auto off cancels the queued debounce', async ({ page }) => {
  await mount(page);
  await page.evaluate(() => { window.floorHarness.select(1); window.floorHarness.auto(false); });
  await page.waitForTimeout(300);
  expect(await page.evaluate(() => window.requests.length)).toBe(0);
});

test('selecting a different design clears completed floor plan while auto is off', async ({ page }) => {
  await mount(page);
  await run(page, 1);
  await settle(page, 0, { design_id: 'prior-plan' });
  await expect.poll(async () => (await state(page)).result).toEqual({ design_id: 'prior-plan' });
  await page.evaluate(() => window.floorHarness.auto(false));
  await page.evaluate(() => window.floorHarness.select(2));
  await expect.poll(async () => (await state(page)).result).toBe(null);
  await page.waitForTimeout(300);
  expect(await page.evaluate(() => window.requests.length)).toBe(1);
});

test('failed current request can retry the same design through automatic selection', async ({ page }) => {
  await mount(page);
  await page.evaluate(() => window.floorHarness.select(1));
  await expect.poll(() => page.evaluate(() => window.requests.length)).toBe(1);
  await page.evaluate(() => window.requests[0].reject(new Error('current failure')));
  await expect.poll(async () => (await state(page)).error).toBe('current failure');
  await page.evaluate(() => window.floorHarness.select(1));
  await expect.poll(() => page.evaluate(() => window.requests.length)).toBe(2);
  await settle(page, 1, { design_id: 'retry' });
  await expect.poll(async () => (await state(page)).result).toEqual({ design_id: 'retry' });
});
