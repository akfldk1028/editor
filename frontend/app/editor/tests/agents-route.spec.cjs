const { test, expect } = require('@playwright/test');

test('native agent cards preserve search and details without confusing connection with implementation', async ({ page }) => {
  let fail = false;
  await page.route('**/api/v1/platform/agents', r => r.fulfill(fail ? { status: 503, json: { detail: 'unavailable' } } : { json: [
    { agent_id: 'systems', label: 'Systems', capabilities: ['mep'], connection_status: 'available', implementation_status: 'partial', checked_at: '2026-10-05T01:00:00Z', evidence_ref: null },
    { agent_id: 'interior', label: 'InteriorDesign', capabilities: [], connection_status: 'unknown', implementation_status: 'unknown', checked_at: null, evidence_ref: null },
  ] }));
  await page.goto(process.env.EDITOR_TEST_URL + '/agents');
  await expect(page.getByRole('heading', { name: 'A2A Agents' })).toBeVisible();
  await page.getByRole('textbox', { name: 'Search agents' }).fill('systems');
  await expect(page.getByRole('heading', { name: 'InteriorDesign' })).toHaveCount(0);
  const card = page.getByRole('button').filter({ has: page.getByRole('heading', { name: 'Systems', level: 3 }) });
  await card.focus();
  await page.keyboard.press('Enter');
  await page.getByRole('button', { name: 'Show JSON' }).click();
  await expect(page.locator('pre')).toContainText('"implementation_status": "partial"');
  await page.screenshot({ path: 'test-results/native-agent-catalog.png', fullPage: true });
  await page.getByRole('button', { name: 'Close detail panel' }).click();
  fail = true;
  await page.getByRole('button', { name: '목록 새로고침' }).click();
  await expect(page.getByRole('alert').filter({ hasText: '에이전트 목록 연결 실패 (503)' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Systems' })).toHaveCount(0);
});
