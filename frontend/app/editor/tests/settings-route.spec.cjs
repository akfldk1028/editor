const { test, expect } = require('@playwright/test');
const base = process.env.EDITOR_TEST_URL || 'http://127.0.0.1:3003';

test('original settings save and reload through Editor and scope appearance to workspace', async ({ page, request }) => {
  page.setDefaultTimeout(20000);
  const initial = await request.get(`${base}/api/v1/workspace/settings`);
  expect(initial.ok()).toBe(true);
  const original = await initial.json();
  try {
    await page.goto(`${base}/settings`);
    await expect(page.getByRole('heading', { name: 'UI Settings', exact: true })).toBeVisible({ timeout: 30000 });
    await expect(page.getByRole('heading', { name: 'Environment Variables', exact: true })).toBeVisible();
    await page.getByLabel('Human input timeout in minutes').fill('8');
    const saved = page.waitForResponse(response => response.url().endsWith('/api/v1/workspace/settings') && response.request().method() === 'PUT');
    await page.getByLabel('Save UI settings', { exact: true }).click();
    expect((await saved).status()).toBe(200);
    await expect(page.getByLabel('Save UI settings', { exact: true })).toBeDisabled();
    await page.getByRole('radio', { name: 'Ocean theme' }).click();
    await expect(page.locator('.agent-workspace')).toHaveAttribute('data-theme', 'ocean');
    await page.getByLabel('Language', { exact: true }).selectOption('en-US');
    await page.reload();
    await expect(page.getByLabel('Human input timeout in minutes')).toHaveValue('8');
    await expect(page.getByRole('heading', { name: 'Settings', exact: true })).toBeVisible();
    await expect(page.locator('.agent-workspace')).toHaveAttribute('data-theme', 'ocean');
    expect(await page.locator('html').getAttribute('data-theme')).not.toBe('ocean');
    await page.screenshot({ path: 'test-results/settings-native.png', fullPage: true });
  } finally {
    const current = await (await request.get(`${base}/api/v1/workspace/settings`)).json();
    const restored = await request.put(`${base}/api/v1/workspace/settings`, { data: { ...current, config: original.config } });
    expect(restored.ok()).toBe(true);
  }
});
