const { test, expect } = require('@playwright/test');
const base = process.env.EDITOR_TEST_URL || 'http://127.0.0.1:3003';

async function createTeam(request) {
  const result = await request.post(`${base}/api/v1/workspace/teams`, { headers: { Origin: base }, data: { component: {
    label: `Native UserProxy ${Date.now()}`, provider: 'autogen_agentchat.teams.RoundRobinGroupChat', component_type: 'team',
    config: { participants: [{ provider: 'autogen_agentchat.agents.UserProxyAgent', component_type: 'agent', config: { name: 'human' } }], max_turns: 1 },
  } } });
  expect(result.ok()).toBe(true);
  return result.json();
}

test('actual Playground runs UserProxy, restores pending input, persists history and stops input wait', async ({ page, request }) => {
  const team = await createTeam(request);
  await page.goto(`${base}/playground?team_id=${team.id}`);
  await expect(page.getByLabel('Select a team')).toHaveValue(String(team.id));
  const prompt = page.getByLabel('Task or input');
  await prompt.fill('Native dialogue verification');
  await page.locator('input[type=file]').setInputFiles({ name: 'context.txt', mimeType: 'text/plain', buffer: Buffer.from('Native attachment record') });
  await page.getByRole('button', { name: 'Send task', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Send input', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Stop execution', exact: true })).toBeVisible();
  await expect(page.getByText(/Native attachment record/)).toBeVisible();
  const boundUrl = page.url();
  expect(boundUrl).toContain('session_id=');
  expect(boundUrl).toContain('run_id=');
  await page.reload();
  await expect(page.getByRole('button', { name: 'Send input', exact: true })).toBeVisible();
  await prompt.fill('Native persisted answer');
  await page.getByRole('button', { name: 'Send input', exact: true }).click();
  await expect(page.getByText('Native persisted answer', { exact: true }).last()).toBeVisible();
  await expect(page.getByText(/Native attachment record/)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Send task', exact: true })).toBeVisible();
  await expect(page).not.toHaveURL(/run_id=/);
  await page.reload();
  await expect(page.getByText('Native persisted answer', { exact: true }).last()).toBeVisible();
  const popupPromise = page.waitForEvent('popup');
  await page.getByRole('button', { name: 'Open flow in new window', exact: true }).click();
  const popup = await popupPromise;
  await expect(popup.getByText('Agent Flow Monitor', { exact: true })).toBeVisible();
  await expect(popup.getByText('Connected', { exact: true })).toBeVisible();
  expect(popup.url()).toContain('channel=');
  await popup.close();
  await prompt.fill('Stop this waiting input');
  await page.getByRole('button', { name: 'Send task', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Send input', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Stop execution', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Send input', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Send task', exact: true })).toBeVisible();
});

test('pending creation locks duplicate sends and team changes, unmount ignores late session', async ({ page, request }) => {
  const team = await createTeam(request);
  let release;
  const gate = new Promise(resolve => { release = resolve });
  let creates = 0;
  let runs = 0;
  await page.route('**/api/v1/workspace/sessions', async route => {
    if (route.request().method() !== 'POST') return route.continue();
    creates++;
    await gate;
    await route.fulfill({ json: { id: 987654, team_id: team.id, name: 'Delayed test' } }).catch(() => {});
  });
  await page.route('**/api/v1/workspace/runs', route => { runs++; return route.fulfill({ status: 500, json: {} }); });
  await page.goto(`${base}/playground?team_id=${team.id}`);
  await expect(page.getByLabel('Select a team')).toHaveValue(String(team.id));
  await page.getByLabel('Task or input').fill('Delayed task');
  await page.getByRole('button', { name: 'Send task', exact: true }).click();
  await expect.poll(() => creates).toBe(1);
  await expect(page.getByRole('button', { name: 'Send task', exact: true })).toBeDisabled();
  await expect(page.getByLabel('Select a team')).toBeDisabled();
  await page.goto(`${base}/mcp`);
  release();
  await expect(page.getByRole('heading', { name: 'MCP', exact: true })).toBeVisible();
  expect(runs).toBe(0);
});
