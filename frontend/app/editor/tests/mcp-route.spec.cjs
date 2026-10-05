const { test, expect } = require('@playwright/test');
const base = process.env.EDITOR_TEST_URL || 'http://127.0.0.1:3003';

async function addServer(page, name = 'Fixture MCP') {
  await page.getByRole('button', { name: 'Add Server', exact: true }).first().click();
  const dialog = page.getByRole('dialog', { name: 'Add MCP server' });
  await dialog.getByLabel('Server Name').fill(name);
  await dialog.getByLabel('Command', { exact: false }).fill('python');
  await dialog.getByLabel('Environment Variables', { exact: false }).fill('MCP_FIXTURE_SECRET=memory-only');
  await dialog.getByRole('button', { name: 'Add Server', exact: true }).click();
}

test('MCP original workbench connects, calls tools, reads resources and removes session', async ({ page }) => {
  const posted = [];
  let removed = 0;
  await page.route('**/api/v1/workspace/mcp/connections**', async route => {
    const request = route.request();
    if (request.method() === 'DELETE') { removed++; return route.fulfill({ json: { closed: true } }); }
    const body = request.postDataJSON(); posted.push(body);
    if (body.server_params) return route.fulfill({ json: { connection_id: 'fixture', capabilities: { tools: {}, resources: {} } } });
    const data = body.operation === 'list_tools' ? { tools: [{ name: 'echo', description: 'Fixture echo', inputSchema: { type: 'object', properties: { text: { type: 'string' } } } }] }
      : body.operation === 'call_tool' ? { content: [{ type: 'text', text: body.arguments.text }] }
      : body.operation === 'list_resources' ? { resources: [{ uri: 'fixture://one', name: 'Fixture resource' }] }
      : { contents: [{ uri: body.uri, text: 'source-bound resource' }] };
    return route.fulfill({ json: { type: 'operation_result', operation: body.operation, data } });
  });
  await page.goto(`${base}/mcp`);
  await addServer(page);
  await page.getByRole('button', { name: 'Check health of Fixture MCP', exact: true }).click();
  await page.getByRole('button', { name: /Fixture MCP Stdio Connected/ }).click();
  await page.getByRole('button', { name: 'echo Fixture echo', exact: true }).click();
  await page.getByLabel('Input (JSON)').fill('{"text":"native-echo"}');
  await page.getByRole('button', { name: 'Execute', exact: true }).click();
  await expect(page.locator('pre').filter({ hasText: 'native-echo' })).toBeVisible();
  await page.getByRole('button', { name: 'List Resources', exact: true }).click();
  await page.getByRole('button', { name: 'Fixture resource', exact: true }).click();
  await expect(page.getByTestId('mcp-resource-output')).toContainText('source-bound resource');
  expect(posted[0].server_params.env).toEqual({ MCP_FIXTURE_SECRET: 'memory-only' });
  const stored = await page.evaluate(() => localStorage.getItem('editor:mcp-servers:v1'));
  expect(stored).not.toContain('memory-only');
  expect(stored).not.toContain('MCP_FIXTURE_SECRET');
  await page.getByRole('button', { name: 'Remove Fixture MCP', exact: true }).click();
  await expect(page.getByText('No MCP servers configured')).toBeVisible();
  await expect.poll(() => removed).toBe(1);
});

test('MCP connection failure remains visible and never leaves connecting status', async ({ page }) => {
  await page.route('**/api/v1/workspace/mcp/connections', route => route.fulfill({ status: 502, json: { detail: 'unavailable' } }));
  await page.goto(`${base}/mcp`);
  await addServer(page, 'Unavailable MCP');
  await page.getByRole('button', { name: 'Check health of Unavailable MCP', exact: true }).click();
  await expect(page.getByRole('alert').filter({ hasText: 'MCP request failed' })).toContainText('502');
  await expect(page.getByRole('button', { name: 'Check health of Unavailable MCP', exact: true })).toBeEnabled();
  await expect(page.getByText('Error', { exact: true })).toBeVisible();
});

test('MCP workbench executes the actual native stdio fixture and reads its resource', async ({ page }) => {
  await page.goto(`${base}/mcp`);
  await page.getByRole('button', { name: 'Add Server', exact: true }).first().click();
  const dialog = page.getByRole('dialog', { name: 'Add MCP server' });
  await dialog.getByLabel('Server Name').fill('Native verification fixture');
  await dialog.getByLabel('Command', { exact: false }).fill('C:/Python313/python.exe');
  await dialog.getByLabel('Arguments (comma-separated)').fill('D:/Data/25_ACE/editor/backend/tests/fixtures/workspace_mcp_server.py');
  await dialog.getByRole('button', { name: 'Add Server', exact: true }).click();
  await page.getByRole('button', { name: 'Check health of Native verification fixture', exact: true }).click();
  const server = page.getByRole('button', { name: /Native verification fixture Stdio Connected/ });
  await expect(server).toBeVisible();
  await server.click();
  await page.getByRole('button', { name: /^add\b/ }).click();
  await page.getByLabel('Input (JSON)').fill('{"a":17,"b":25}');
  await page.getByRole('button', { name: 'Execute', exact: true }).click();
  await expect(page.locator('pre').filter({ hasText: '42' })).toBeVisible();
  await page.getByRole('button', { name: 'List Resources', exact: true }).click();
  const read = page.waitForResponse(response => response.url().endsWith('/operations') && response.request().postDataJSON()?.operation === 'read_resource');
  await page.getByRole('button', { name: /^note$|^test:\/\/note$/ }).click();
  expect((await read).ok()).toBe(true);
  await expect(page.getByTestId('mcp-resource-output')).toContainText('Native resource');
  await page.getByRole('button', { name: 'Remove Native verification fixture', exact: true }).click();
  await expect(page.getByText('No MCP servers configured')).toBeVisible();
});
