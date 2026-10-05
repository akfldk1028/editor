const { test, expect } = require('@playwright/test');
const base = process.env.EDITOR_TEST_URL || 'http://127.0.0.1:3003';

async function archive(request, runId) {
  const suffix = runId ? `?run_id=${encodeURIComponent(runId)}` : '';
  const response = await request.get(`${base}/api/v1/design/maas/portfolio-evaluations/${suffix}`);
  expect(response.ok()).toBe(true);
  return response.json();
}

test('portfolio keeps the original empty latest evaluation and lists older native archives', async ({ page, request }) => {
  const latest = await archive(request);
  expect(latest.candidate_count).toBe(0);
  expect(latest.runs.length).toBeGreaterThan(1);
  await page.goto(`${base}/design/language`);
  await page.getByRole('tab', { name: 'MASS PORTFOLIO', exact: true }).click();
  const selector = page.getByRole('combobox', { name: 'Evaluation archive run' });
  await expect(selector).toHaveValue(latest.run_id, { timeout: 30000 });
  await expect(selector.locator('option')).toHaveCount(latest.runs.length);
  await expect(page.getByText('This archived evaluation run contains no candidates.')).toBeVisible();
  await expect(page.getByRole('list', { name: 'All evaluated MASS candidates' }).getByRole('listitem')).toHaveCount(0);
  expect(new URL(page.url()).searchParams.has('evaluation_run')).toBe(false);
});

test('selecting a populated native evaluation preserves cards, status, URL and reload', async ({ page, request }) => {
  const latest = await archive(request);
  const row = [...latest.runs].reverse().find(run => run.candidate_count > 0);
  expect(row).toBeTruthy();
  const older = await archive(request, row.run_id);
  await page.goto(`${base}/design/language`);
  await page.getByRole('tab', { name: 'MASS PORTFOLIO', exact: true }).click();
  const selector = page.getByRole('combobox', { name: 'Evaluation archive run' });
  await expect(selector).toHaveValue(latest.run_id, { timeout: 30000 });
  await selector.selectOption(row.run_id);
  await expect(page).toHaveURL(new RegExp(`evaluation_run=${encodeURIComponent(row.run_id)}`));
  const cards = page.getByRole('list', { name: 'All evaluated MASS candidates' }).getByRole('listitem');
  await expect(cards).toHaveCount(older.candidate_count, { timeout: 30000 });
  await expect(cards.first()).toHaveAttribute('data-status', older.candidates[0].overall_status);
  await expect(page.locator('.mass-portfolio > header strong')).toHaveText(row.run_id);
  await page.reload();
  await expect(page.getByRole('tab', { name: 'MASS PORTFOLIO', exact: true })).toHaveAttribute('aria-selected', 'true');
  await expect(selector).toHaveValue(row.run_id, { timeout: 30000 });
  await expect(cards).toHaveCount(older.candidate_count);
  await expect(cards.first()).toHaveAttribute('data-status', older.candidates[0].overall_status);
  await expect(page.getByText('This archived evaluation run contains no candidates.')).toHaveCount(0);
  await selector.selectOption(latest.run_id);
  await expect(cards).toHaveCount(0);
  await expect(page.getByText('This archived evaluation run contains no candidates.')).toBeVisible();
});
