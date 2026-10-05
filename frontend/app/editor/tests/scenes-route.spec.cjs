const { test, expect } = require('@playwright/test');
const { createServer } = require('node:http');

test('saved scenes distinguish upstream failure, invalid data and an empty store, then retry', async ({ page }) => {
  let status = 503;
  let payload = { error: 'unavailable' };
  const requests = [];
  const upstream = createServer((request, response) => {
    requests.push(request.url);
    response.writeHead(status, { 'Content-Type': 'application/json' });
    response.end(JSON.stringify(payload));
  });
  await new Promise(resolve => upstream.listen(0, '127.0.0.1', resolve));
  try {
    const host = `127.0.0.1:${upstream.address().port}`;
    await page.route('**/scenes', route => route.continue({ headers: {
      ...route.request().headers(), 'x-forwarded-host': host, 'x-forwarded-proto': 'http',
    } }));
    await page.goto(`${process.env.EDITOR_TEST_URL}/scenes`);
    await expect(page.getByRole('main').getByRole('alert')).toContainText('Unable to load saved scenes');
    await expect(page.getByText('No scenes yet.', { exact: false })).toHaveCount(0);
    status = 200;
    payload = {};
    await page.getByRole('link', { name: 'Retry', exact: true }).click();
    await expect(page.getByRole('main').getByRole('alert')).toContainText('Unable to load saved scenes');
    payload = { scenes: [] };
    await page.getByRole('link', { name: 'Retry', exact: true }).click();
    await expect(page.getByText('No scenes yet.', { exact: false })).toBeVisible();
    await expect(page.getByRole('main').getByRole('alert')).toHaveCount(0);
    expect(requests).toEqual(['/api/scenes?limit=50', '/api/scenes?limit=50', '/api/scenes?limit=50']);
  } finally {
    await new Promise(resolve => upstream.close(resolve));
  }
});
