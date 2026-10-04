import { test, expect } from '@playwright/test';

test('routing: agent deep link, search, history and reload', async ({ page }) => {
  await page.route('**/api/v1/platform/agents', route => route.fulfill({json: [{
    agent_id: 'systems', label: 'Systems', capabilities: ['systems.review'],
    implementation_status: 'partial', connection_status: 'unknown', checked_at: null, evidence_ref: null,
  }]}));
  await page.goto('/agents');
  await expect(page.getByRole('heading', { name: 'Systems', exact: true })).toBeVisible();
  await expect(page.getByText('partial', { exact: true })).toBeVisible();
  await page.getByRole('textbox', {name:'에이전트 검색'}).fill('absent');
  await expect(page.getByText('검색 결과가 없습니다.')).toBeVisible();
  await page.getByRole('button', {name:'PLANM Planning'}).click();
  await expect(page).toHaveURL(/\/planm$/);
  await page.goBack();
  await expect(page).toHaveURL(/\/agents$/);
  await page.reload();
  await expect(page.getByRole('heading', {name:'Systems', exact:true})).toBeVisible();
});

test('routing: API failure never becomes empty success; retry recovers', async ({page}) => {
  let fail = true;
  await page.route('**/api/v1/platform/agents', route => fail
    ? route.fulfill({status:503, json:{detail:'unavailable'}})
    : route.fulfill({json:[]}));
  await page.goto('/agents');
  await expect(page.getByRole('alert')).toContainText('503');
  await expect(page.getByText('표시할 에이전트가 없습니다.')).toHaveCount(0);
  fail = false;
  await page.getByRole('button', {name:'새로고침'}).click();
  await expect(page.getByText('표시할 에이전트가 없습니다.')).toBeVisible();
});
