const { test, expect } = require('@playwright/test');

test('flow preserves project/run scope and original controls without invented participants', async ({ page }) => {
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  const project = { project_id: 'p1', owner_project_id: 'owner1', branch_id: 'main', scene_id: 'scene1', scene_revision: 0, scene_project_id: null };
  const run = { run_id: 'r1', request_id: 'req1', receipt_task_ids: ['t1'], owner_project_id: 'owner1', branch_id: 'main', status: 'partial', goal: 'health', pending_input: true,
    communications_available: true, communications_truncated: false, communications: [{ id: 'c1', task_id: 't1', tool: 'health', agent: 'systems', state: 'blocked', request_text: '설비 연결 확인', response_text: '설정 필요', transport: 'a2a', truncated: false }] };
  await page.route('**/api/v1/platform/projects', r => r.fulfill({ json: [project] }));
  await page.route('**/api/v1/platform/projects/p1/runs', r => r.fulfill({ json: [run] }));
  await page.route('**/api/v1/platform/runs/r1?project_id=p1', r => r.fulfill({ json: run }));
  await page.goto(process.env.EDITOR_TEST_URL + '/flow?project_id=p1&run_id=r1');
  await expect(page.getByTestId('ag-light-react-flow')).toHaveAttribute('data-node-count', '2');
  await expect(page.getByTestId('ag-light-react-flow')).toHaveAttribute('data-edge-count', '2');
  await page.getByRole('button', { name: '전체화면', exact: true }).click();
  await expect(page.getByRole('button', { name: '전체화면 해제' })).toBeVisible();
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: '라벨 숨김' }).click();
  await expect(page.getByTestId('ag-light-edge-overlay').locator('text')).toHaveCount(0);
  await page.getByRole('button', { name: '라벨 표시' }).click();
  await page.locator('.react-flow__node').filter({ hasText: 'systems' }).click();
  await expect(page.getByRole('heading', { name: 'systems · 요청/응답' })).toBeVisible();
  await page.getByRole('button', { name: '옵션', exact: true }).click();
  await page.getByRole('menuitemcheckbox', { name: 'Grid' }).click();
  await expect(page.locator('.react-flow__background')).toHaveCount(0);
  await page.getByRole('menuitemcheckbox', { name: 'Reset' }).click();
  await page.getByRole('link', { name: '대화 타임라인', exact: true }).click();
  await expect(page).toHaveURL(/\/dialogue\?project_id=p1&run_id=r1$/);
  await expect(page.getByText('설비 연결 확인', { exact: true })).toBeVisible();
  await page.getByRole('navigation', { name: '대화 표시 방식' }).getByRole('link', { name: '협업 흐름도' }).click();
  await expect(page).toHaveURL(/\/flow\?project_id=p1&run_id=r1$/);
  await page.reload();
  await expect(page.getByTestId('ag-light-react-flow')).toHaveAttribute('data-node-count', '2');
  expect(errors).toEqual([]);
});
