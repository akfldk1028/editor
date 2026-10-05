const { test, expect } = require('@playwright/test');
const base = process.env.EDITOR_TEST_URL || 'http://127.0.0.1:3003';

test('native deployment preserves useful controls and generates Editor commands only', async ({ page }) => {
  await page.goto(`${base}/deploy`);
  await expect(page.getByRole('heading', { name: 'Deploy', exact: true })).toBeVisible();
  for (const title of ['Local Development', 'Docker Deployment', 'Cloud Deployment', 'Launch Configuration', 'Environment Variables', 'API Endpoints Reference', 'Deployment Status']) {
    await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible();
  }
  await page.getByLabel('Backend port', { exact: true }).fill('18450');
  await expect(page.getByTestId('backend-command')).toContainText('backend.app.main:app');
  await expect(page.getByTestId('backend-command')).toContainText('--port 18450');
  await expect(page.getByTestId('frontend-command')).toContainText('EDITOR_BACKEND_URL');
  await expect(page.getByTestId('frontend-command')).toContainText('18450');
  await expect(page.getByTestId('backend-command')).toContainText("EDITOR_PUBLIC_URL = 'http://127.0.0.1:3003'");
  await expect(page.locator('main')).not.toContainText('autogenstudio');
  await page.getByLabel('Backend port', { exact: true }).fill('0');
  await expect(page.getByRole('button', { name: 'Copy backend command', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'Reset configuration', exact: true }).click();
  await expect(page.getByLabel('Backend port', { exact: true })).toHaveValue('18449');
});

test('deployment sidebar navigation, live health, clipboard and reload work', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.goto(`${base}/settings`);
  const navigation = page.getByRole('complementary', { name: 'Main navigation' });
  await navigation.getByRole('link', { name: 'Deploy', exact: true }).click();
  await expect(page).toHaveURL(`${base}/deploy`);
  await expect(navigation.getByRole('link', { name: 'Deploy', exact: true })).toHaveAttribute('aria-current', 'page');
  await expect(page.getByTestId('deployment-status')).toContainText('Connected');
  await page.getByRole('button', { name: 'Copy backend command', exact: true }).click();
  const command = await page.evaluate(() => navigator.clipboard.readText());
  expect(command).toContain('backend.app.main:app');
  expect(command.split('\n')).toHaveLength(3);
  expect(command).not.toContain('\\n');
  expect(command.split(/\r?\n/)[0]).toBe("Set-Location -LiteralPath 'D:\\Data\\25_ACE\\editor'");
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Deploy', exact: true })).toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL(`${base}/settings`);
});

test('deployment environment editor masks values and never persists secrets', async ({ page }) => {
  await page.goto(`${base}/deploy`);
  await page.getByRole('button', { name: 'OPENAI_API_KEY', exact: true }).click();
  await page.getByLabel('Value for OPENAI_API_KEY', { exact: true }).fill('deployment-test-secret');
  await expect(page.getByLabel('Value for OPENAI_API_KEY', { exact: true })).toHaveAttribute('type', 'password');
  await expect(page.getByTestId('environment-preview')).not.toContainText('deployment-test-secret');
  expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain('deployment-test-secret');
  await page.reload();
  await expect(page.getByLabel('Value for OPENAI_API_KEY', { exact: true })).toHaveCount(0);
});

test('deployment status reflects backend errors instead of claiming deployed', async ({ page }) => {
  await page.route('**/api/v1/workspace/health', route => route.fulfill({ status: 503, json: { detail: 'unavailable' } }));
  await page.goto(`${base}/deploy`);
  await expect(page.getByTestId('deployment-status')).toContainText('Disconnected', { timeout: 20000 });
  await expect(page.getByTestId('deployment-status')).toContainText('Not deployed');
});
