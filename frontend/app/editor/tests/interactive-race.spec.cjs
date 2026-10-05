const { test, expect } = require('@playwright/test');
const { execFileSync } = require('node:child_process');
const { mkdtempSync, readFileSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const path = require('node:path');
let directory;
let script;
test.beforeAll(() => {
  directory = mkdtempSync(path.join(tmpdir(), 'editor-interactive-hook-'));
  const bundle = path.join(directory, 'harness.js');
  const bun = process.env.BUN_BINARY || (process.platform === 'win32' ? path.join(process.env.APPDATA, 'npm/node_modules/bun/bin/bun.exe') : 'bun');
  execFileSync(bun, ['build', path.join(__dirname, 'interactive-hook-harness.tsx'), '--target', 'browser', '--outfile', bundle, '--define', 'process.env.NODE_ENV="development"'], { stdio: 'pipe' });
  script = readFileSync(bundle, 'utf8');
});
test.afterAll(() => {
  if (directory && path.dirname(path.resolve(directory)) === path.resolve(tmpdir()) && path.basename(directory).startsWith('editor-interactive-hook-')) {
    rmSync(directory, { recursive: true, force: true });
  }
});

async function mount(page) {
  await page.setContent('<div id="root"></div>');
  await page.evaluate(() => {
    window.process = { env: { NODE_ENV: 'development', NEXT_PUBLIC_BASE_PATH: '' } };
    window.requests = [];
    window.fetch = (url, init) => {
      if (!String(url).includes('/interactive/') && !String(url).includes('/aesthetic/') && !String(url).includes('/maas/legal-variants/')) {
        return Promise.resolve({ ok: true, json: async () => ({ status: true, messages: [] }) });
      }
      return new Promise((resolve, reject) => window.requests.push({ url, init, reject, resolve: value => resolve({ ok: true, json: async () => value }) }));
    };
  });
  await page.addScriptTag({ content: script });
  await expect(page.locator('#state')).toContainText('"job":"job-old"');
  await page.evaluate(() => window.interactiveHarness.setMessage('revise this mass'));
  await expect(page.locator('#state')).toContainText('revise this mass');
}
const state = async page => JSON.parse(await page.locator('#state').textContent());
const invoke = (page, method) => page.evaluate(method => { void window.interactiveHarness[method]({ type: 'translate' }); }, method);
const settle = (page, index, result) => page.evaluate(({ index, result }) => window.requests[index].resolve(result), { index, result });
const feature = { type: 'Feature', geometry: { type: 'Polygon', coordinates: [] }, properties: { design_id: 0, design_uid: 'old-uid' } };
const patch = { mode: 'dry_run', candidates: [], notes: [] };

test('aesthetic accepts canonical numeric design ID zero', async ({ page }) => {
  await mount(page);
  await invoke(page, 'generateAesthetic');
  await expect.poll(() => page.evaluate(() => window.requests.length)).toBe(1);
  expect(await page.evaluate(() => window.requests[0].url)).toContain('/jobs/job-old/results/0/aesthetic/');
  expect(await page.evaluate(() => JSON.parse(window.requests[0].init.body).design_uid)).toBe('old-uid');
  await settle(page, 0, { status: 'complete', image_url: 'test-image' });
  await expect.poll(async () => (await state(page)).texture).toEqual({ status: 'complete', image_url: 'test-image' });
});

for (const method of ['submit', 'buildPreview', 'buildMaasVariants', 'applyOperation', 'generateAesthetic']) {
  test(`${method} cannot publish stale geometry or texture after job and UID switch`, async ({ page }) => {
    await mount(page);
    let index = 0;
    if (method === 'buildPreview') {
      await invoke(page, 'submit');
      await settle(page, 0, patch);
      await expect.poll(async () => (await state(page)).result).toEqual(patch);
      index = 1;
    }
    await invoke(page, method);
    await expect.poll(() => page.evaluate(() => window.requests.length)).toBe(index + 1);
    await page.evaluate(() => window.interactiveHarness.switchContext());
    await expect(page.locator('#state')).toContainText('"job":"job-new"');
    const result = method === 'submit' ? patch : method === 'buildPreview' ? { candidates: [{ id: 'old', mass_geojson: feature }] }
      : method === 'buildMaasVariants' ? { feature_collection: { features: [feature] }, notes: [] }
      : method === 'applyOperation' ? { feature, notes: [] } : { status: 'complete', image_url: 'stale-image' };
    await settle(page, index, result);
    await expect.poll(async () => {
      const s = await state(page);
      return [s.applied, s.texture, s.result, s.preview, s.aesthetic, s.error, s.loading];
    }).toEqual([null, null, null, null, null, '', [false, false, false, false]]);
    expect(await page.evaluate(index => window.requests[index].init.signal?.aborted, index)).toBe(true);
  });
}


for (const next of [{ job: 'job-new', uid: 'old-uid' }, { job: 'job-old', uid: 'new-uid' }]) {
  test(`operation invalidates when only ${next.job === 'job-new' ? 'job' : 'UID'} changes`, async ({ page }) => {
    await mount(page);
    await invoke(page, 'applyOperation');
    await page.evaluate(next => window.interactiveHarness.switchContext(next), next);
    await expect.poll(async () => (await state(page)).context).toEqual(next);
    await settle(page, 0, { feature, notes: [] });
    await expect.poll(async () => (await state(page)).applied).toBe(null);
    expect(await page.evaluate(() => window.requests[0].init.signal.aborted)).toBe(true);
  });
}

test('new interactive intent owns loading and ignores old rejection; unmount aborts outstanding work', async ({ page }) => {
  await mount(page);
  await invoke(page, 'applyOperation');
  await invoke(page, 'generateAesthetic');
  await page.evaluate(() => window.requests[0].reject(new Error('old operation failure')));
  await expect.poll(async () => (await state(page)).error).toBe('');
  expect((await state(page)).loading).toEqual([false, false, false, true]);
  await settle(page, 1, { status: 'complete', image_url: 'current' });
  await expect.poll(async () => (await state(page)).texture).toEqual({ status: 'complete', image_url: 'current' });
  await invoke(page, 'submit');
  await page.evaluate(() => window.interactiveHarness.unmount());
  expect(await page.evaluate(() => window.requests[2].init.signal.aborted)).toBe(true);
  await settle(page, 2, patch);
  await expect(page.locator('#state')).toHaveCount(0);
});
