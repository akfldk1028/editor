const { test, expect } = require('@playwright/test');
const base = process.env.EDITOR_TEST_URL || 'http://127.0.0.1:3003';
test('original gallery categories and import persist a team in native builder', async ({ page, request }) => {
  page.setDefaultTimeout(20000);
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  const label = `Migration test ${Date.now()}`;
  const component = { label, provider: 'autogen_agentchat.teams.RoundRobinGroupChat', component_type: 'team', config: { participants: [{ provider: 'autogen_agentchat.agents.AssistantAgent', component_type: 'agent', label: 'Test assistant', config: { name: 'test_assistant', model_client: { provider: 'autogen_ext.models.openai.OpenAIChatCompletionClient', component_type: 'model', config: { model: 'test-only' } } } }] } };
  const result = await request.post(`${base}/api/v1/workspace/galleries`, { data: { config: { name: label, metadata: { description: 'Browser verification fixture' }, components: { teams: [component], agents: [], models: [], tools: [], workbenches: [], terminations: [] } } } });
  expect(result.status()).toBe(201);
  const gallery = await result.json();
  try {
    await page.goto(`${base}/gallery`, { waitUntil: 'domcontentloaded' });
    await expect(page.getByRole('heading', { name: 'Gallery', exact: true })).toBeVisible();
    await page.getByRole('button', { name: `View gallery: ${label}` }).click();
    for (const category of ['Teams', 'Agents', 'Models', 'Tools', 'Workbenches', 'Terminations']) {
      await page.getByRole('tab', { name: new RegExp(category) }).click();
    }
    await page.screenshot({ path: 'test-results/gallery-native.png', fullPage: true });
    await page.getByLabel('Back to gallery list').click();
    await page.getByLabel(`Import team from ${label}`).click();
    await page.getByRole('radio').filter({ hasText: label }).click();
    await page.getByRole('button', { name: 'Import Team', exact: true }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await page.goto(`${base}/build`);
    await expect(page.getByRole('heading', { name: label, exact: true })).toBeVisible({ timeout: 30000 });
    await page.getByRole('heading', { name: label, exact: true }).click();
    await page.getByLabel('Show JSON view').click();
    await expect(page.getByText('test_assistant', { exact: false }).first()).toBeVisible();
    await page.getByLabel('Enter edit mode').click();
    await page.getByLabel('Edit JSON', { exact: true }).click();
    await page.getByLabel('Edit JSON configuration').fill(JSON.stringify({ ...component, config: { participants: 'broken' } }));
    await page.getByLabel('Apply JSON changes').click();
    await expect(page.getByText('participants must be a list')).toBeVisible();
    await page.getByLabel('Edit JSON configuration').fill(JSON.stringify({ ...component, description: 'Verified native edit' }));
    await page.getByLabel('Apply JSON changes').click();
    await page.getByLabel('Undo', { exact: true }).click();
    await expect(page.getByLabel('Undo', { exact: true })).toBeDisabled();
    await page.getByLabel('Redo', { exact: true }).click();
    await expect(page.getByLabel('Redo', { exact: true })).toBeDisabled();
    await page.getByLabel('Close graph panel', { exact: true }).click();
    await expect(page.getByRole('alertdialog', { name: 'Unsaved changes' })).toBeVisible();
    await page.getByRole('button', { name: 'Stay', exact: true }).click();
    await page.locator('nav a[href="/gallery"]').click();
    await expect(page.getByRole('alertdialog', { name: 'Unsaved changes' })).toBeVisible();
    await page.getByRole('button', { name: 'Stay', exact: true }).click();
    await expect(page).toHaveURL(`${base}/build`);
    const saved = page.waitForResponse(response => response.request().method() === 'PUT' && response.url().includes('/api/v1/workspace/teams/'));
    await page.getByLabel('Save team changes').click();
    expect((await saved).status()).toBe(200);
    const savedTeams = await (await request.get(`${base}/api/v1/workspace/teams`)).json();
    expect(savedTeams.find(team => team.component?.label === label).component.description).toBe('Verified native edit');
    await page.getByLabel('Toggle pattern selector').click();
    await page.screenshot({ path: 'test-results/team-builder-native.png', fullPage: true });
    await page.reload();
    await expect(page.getByRole('heading', { name: label, exact: true })).toBeVisible({ timeout: 30000 });
    expect(pageErrors).toEqual([]);
  } finally {
    const teams = await (await request.get(`${base}/api/v1/workspace/teams`)).json();
    for (const team of teams.filter(team => team.component?.label === label)) await request.delete(`${base}/api/v1/workspace/teams/${team.id}`);
    await request.delete(`${base}/api/v1/workspace/galleries/${gallery.id}`);
  }
});


test('editing a termination limit preserves the original AND operator', async ({ page, request }) => {
  const label = `AND review ${Date.now()}`;
  const component = { provider: 'autogen_agentchat.teams.RoundRobinGroupChat', component_type: 'team', label, config: {
    participants: [{ provider: 'autogen_agentchat.agents.UserProxyAgent', component_type: 'agent', config: { name: 'user_proxy' } }],
    termination_condition: { provider: 'autogen_agentchat.conditions.AndTermination', component_type: 'termination', config: { conditions: [
      { provider: 'autogen_agentchat.conditions.MaxMessageTermination', component_type: 'termination', config: { max_messages: 10 } },
      { provider: 'autogen_agentchat.conditions.TimeoutTermination', component_type: 'termination', config: { timeout_seconds: 120 } },
    ] } },
  } };
  const response = await request.post(`${base}/api/v1/workspace/teams`, { data: { component } });
  expect(response.status()).toBe(201);
  const team = await response.json();
  try {
    await page.goto(`${base}/build`);
    await page.getByRole('heading', { name: label, exact: true }).click();
    await page.getByLabel('Enter edit mode').click();
    await page.getByRole('button', { name: /Termination Conditions/ }).click();
    await page.getByLabel('Max messages', { exact: true }).fill('15');
    const saved = page.waitForResponse(response => response.request().method() === 'PUT' && response.url().endsWith(`/teams/${team.id}`));
    await page.getByLabel('Save team changes').click();
    expect((await saved).status()).toBe(200);
    const updated = await (await request.get(`${base}/api/v1/workspace/teams/${team.id}`)).json();
    expect(updated.component.config.termination_condition.provider).toBe('autogen_agentchat.conditions.AndTermination');
    expect(updated.component.config.termination_condition.config.conditions[0].config.max_messages).toBe(15);
  } finally { await request.delete(`${base}/api/v1/workspace/teams/${team.id}`); }
});
