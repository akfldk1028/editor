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


test('saving UI preferences preserves a subsequent unsaved environment edit', async ({ page }) => {
  let settings = { id: 1, version: 0, config: { ui: { show_llm_call_events: false, expanded_messages_by_default: false, show_agent_flow_by_default: false, human_input_timeout_minutes: 3 }, environment: [] } };
  await page.route('**/api/v1/workspace/settings', async route => {
    if (route.request().method() === 'PUT') settings = { ...route.request().postDataJSON(), version: settings.version + 1 };
    await route.fulfill({ json: settings });
  });
  await page.goto(`${base}/settings`);
  await page.getByLabel('New variable name').fill('REVIEW_DRAFT');
  await page.getByLabel('New variable value').fill('saved-value');
  await page.getByLabel('Add environment variable', { exact: true }).click();
  await page.getByLabel('Save environment variables', { exact: true }).click();
  await expect(page.getByLabel('Save environment variables', { exact: true })).toBeDisabled();
  await page.getByRole('textbox', { name: 'Value for REVIEW_DRAFT', exact: true }).fill('unsaved-value');
  await page.getByLabel('Human input timeout in minutes').fill('9');
  await page.getByLabel('Save UI settings', { exact: true }).click();
  await expect(page.getByLabel('Save UI settings', { exact: true })).toBeDisabled();
  await expect(page.getByRole('textbox', { name: 'Value for REVIEW_DRAFT', exact: true })).toHaveValue('unsaved-value');
});
