const { test, expect } = require('@playwright/test');
const { execFileSync } = require('node:child_process');
const { mkdtempSync, readFileSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const path = require('node:path');
const directory = mkdtempSync(path.join(tmpdir(), 'editor-stream-hook-'));
const bundle = path.join(directory, 'harness.js');
const bun = process.env.BUN_BINARY || (process.platform === 'win32' ? path.join(process.env.APPDATA, 'npm/node_modules/bun/bin/bun.exe') : 'bun');
execFileSync(bun, ['build', path.join(__dirname, 'optimization-hook-harness.tsx'), '--target', 'browser', '--outfile', bundle,
  '--define', 'process.env.NODE_ENV="development"', '--define', 'process.env.NEXT_PUBLIC_BASE_PATH=""'], { stdio: 'pipe' });
const script = readFileSync(bundle, 'utf8');
test.afterAll(() => rmSync(directory, { recursive: true, force: true }));

async function mount(page, polling) {
  await page.route('http://hook.test/**', route => route.fulfill({ contentType: 'text/html', body: '<div id="root"></div>' }));
  await page.goto(`http://hook.test/?e2e=${polling ? '1' : '0'}`);
  await page.evaluate(() => {
    window.pendingRuns = {};
    window.activeTimers = new Map();
    let nextTimer = 0;
    window.setInterval = callback => { window.activeTimers.set(++nextTimer, callback); return nextTimer; };
    window.clearInterval = id => window.activeTimers.delete(id);
    window.fetch = (url) => url.endsWith('/run/')
      ? new Promise((resolve, reject) => { window.pendingRuns[url.split('/').at(-3)] = { resolve, reject }; })
      : Promise.resolve({ ok: true, json: async () => ({ job: { status: 'running' } }) });
    window.sources = [];
    window.EventSource = class extends EventTarget {
      static CONNECTING = 0;
      static CLOSED = 2;
      readyState = 1;
      constructor() { super(); window.sources.push(this); }
      close() { this.readyState = 2; }
    };
  });
  await page.addScriptTag({ content: script });
  await expect(page.locator('#state')).toContainText('"status":"idle"');
}
const state = async page => JSON.parse(await page.locator('#state').textContent());

test('an old polling run rejection cannot fail the next job or clear its timer', async ({ page }) => {
  await mount(page, true);
  await page.evaluate(() => window.optimizationHarness.connect('old'));
  await page.evaluate(() => window.optimizationHarness.connect('new'));
  await page.evaluate(() => window.pendingRuns.old.reject(new Error('old run failed')));
  await expect.poll(async () => (await state(page)).status).toBe('running');
  expect(await page.evaluate(() => window.activeTimers.size)).toBe(1);
  await page.evaluate(() => window.optimizationHarness.reset());
  await page.evaluate(() => window.pendingRuns.new.reject(new Error('unmounted run failed')));
  await expect.poll(async () => (await state(page)).status).toBe('idle');
});

test('new SSE jobs clear prior objective labels and generation budgets', async ({ page }) => {
  await mount(page, false);
  await page.evaluate(() => {
    window.optimizationHarness.connect('old');
    window.sources[0].dispatchEvent(new MessageEvent('started', { data: JSON.stringify({ max_generations: 99, objectives: [{ name: 'old', goal: 'Maximize' }] }) }));
  });
  await expect.poll(async () => (await state(page)).maxGenerations).toBe(99);
  await page.evaluate(() => window.optimizationHarness.connect('new'));
  await expect.poll(async () => (await state(page)).objectives).toEqual([]);
  expect((await state(page)).maxGenerations).toBe(0);
});
