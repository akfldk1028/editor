const { test, expect } = require('@playwright/test');
const base = process.env.EDITOR_TEST_URL || 'http://127.0.0.1:3003';

test('original history keeps detail comparison and archive confirmation with native sessions', async ({ page, request }) => {
  page.setDefaultTimeout(15000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const label = `History verification ${Date.now()}`;
  const response = await request.post(`${base}/api/v1/workspace/teams`, { data: { component: {
    provider: 'test.Team', component_type: 'team', config: {}, label,
  } } });
  expect(response.status()).toBe(201);
  const team = await response.json();
  const sessions = [];
  try {
    for (const suffix of ['A', 'B']) {
      const response = await request.post(`${base}/api/v1/workspace/sessions`, { data: { name: `${label} ${suffix}`, team_id: team.id } });
      expect(response.status()).toBe(201);
      sessions.push(await response.json());
    }
    await page.goto(`${base}/history`);
    await page.getByRole('button', { name: new RegExp(`${label} A`) }).click();
    const detail = page.getByRole('complementary', { name: 'Session detail' });
    await expect(detail.getByText('No runs in this session yet.')).toBeVisible();
    await detail.getByLabel('Delete session').click();
    await expect(detail.getByLabel('Delete session')).toHaveText('Confirm?');
    await page.getByRole('button', { name: new RegExp(`${label} B`) }).click();
    await expect(detail.getByLabel('Delete session')).not.toHaveText('Confirm?');
    await page.getByLabel('Compare sessions', { exact: true }).click();
    for (const suffix of ['A', 'B']) await page.getByRole('button', { name: new RegExp(`${label} ${suffix}`) }).click();
    await expect(page.getByRole('complementary', { name: 'Session detail' })).toHaveCount(2);
    await page.screenshot({ path: 'test-results/history-native.png', fullPage: true });
    const remove = page.getByRole('complementary', { name: 'Session detail' }).first().getByLabel('Delete session');
    await remove.click();
    await expect(remove).toHaveText('Confirm?');
    await remove.click();
    await expect(page.getByRole('button', { name: new RegExp(`${label} A`) })).toHaveCount(0);
    await page.reload();
    await expect(page.getByRole('button', { name: new RegExp(`${label} B`) })).toBeVisible();
    await page.route('**/api/v1/workspace/sessions', route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'History unavailable' }) }));
    await page.reload();
    await expect(page.getByRole('alert').filter({ hasText: 'History unavailable' })).toBeVisible({ timeout: 25000 });
    await expect(page.getByText('No sessions yet.', { exact: false })).toHaveCount(0);
    expect(errors).toEqual([]);
  } finally {
    for (const session of sessions) await request.delete(`${base}/api/v1/workspace/sessions/${session.id}`);
    await request.delete(`${base}/api/v1/workspace/teams/${team.id}`);
  }
});

test('history renders recorded run messages and distinguishes retrieval failure', async ({ page }) => {
  await page.route('**/api/v1/workspace/sessions', route => route.fulfill({ json: [{ id: 901, name: 'Recorded fixture', team_id: 1 }] }));
  await page.route('**/api/v1/workspace/sessions/901/runs', route => route.fulfill({ json: { runs: [{
    id: 902, status: 'error', error_message: 'Recorded tool failure', team_result: { duration: 12.5, task_result: { messages: [] } },
    messages: [
      { config: { source: 'user', content: 'Recorded request' } },
      { config: { source: 'planner', target: 'reviewer', content: 'Check recorded result' } },
      { config: { source: 'reviewer', content: [{ id: 'call-1', name: 'inspect', arguments: '{}' }] } },
      { config: { source: 'reviewer', content: [{ call_id: 'call-1', content: 'Recorded tool output' }] } },
    ],
  }] } }));
  await page.goto(`${base}/history`);
  await page.getByRole('button', { name: /Recorded fixture/ }).click();
  await expect(page.getByRole('button', { name: /Run #902/ })).toContainText('12.5s');
  await page.getByRole('button', { name: /Run #902/ }).click();
  for (const text of ['Recorded request', 'Recorded tool failure', 'Recorded tool output', 'Handing off to']) {
    await expect(page.getByText(text, { exact: false })).toBeVisible();
  }
  await page.route('**/api/v1/workspace/sessions/901/runs', route => route.fulfill({ status: 503, json: { detail: 'Run history unavailable' } }));
  await page.reload();
  await page.getByRole('button', { name: /Recorded fixture/ }).click();
  await expect(page.getByRole('alert').filter({ hasText: 'Run history unavailable' })).toBeVisible({ timeout: 25000 });
  await expect(page.getByText('No runs in this session yet.')).toHaveCount(0);
});
