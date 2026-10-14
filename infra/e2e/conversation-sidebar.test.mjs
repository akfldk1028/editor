import { test } from 'node:test';
import assert from 'node:assert/strict';
import { chromium } from '@playwright/test';
import { baseUrl, byId } from '../host/registry.mjs';

test('conversation sidebar restores history, searches, creates chats and preserves the CAD module', { timeout: 120_000 }, async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 950 } });
  const now = new Date().toISOString();
  const binding = (id, title, conversation = true) => ({ project_id: id, owner_project_id: '검증 프로젝트', branch_id: id,
    scene_id: 'test-scene', scene_revision: 1, scene_project_id: null, conversation, conversation_id: conversation ? `thread-${id}` : null,
    title, created_at: now, updated_at: now });
  const projects = [binding('base', null, false), binding('saved', '저장된 어린이집 대화')];
  const messages = new Map([['thread-saved', [{ id: 'saved-answer', role: 'assistant', agent: 'orchestrator', text: '저장된 대화 내용입니다.', at: now }]]]);
  let failCreation = false;
  let selection = null;
  const card = { id: 'confirmation.layout-test', owner: 'masterplan', title: 'Layout A', status: 'awaiting_confirmation',
    data: { kind: 'layout_selection', candidate_id: 'a', candidate: { metrics: { parking: 23 } }, context: {}, context_hash: 'a'.repeat(64) } };
  await context.route('**/api/v1/platform/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace('/api/v1/platform', '');
    if (path === '/projects') return route.fulfill({ json: projects });
    const create = path.match(/^\/projects\/([^/]+)\/conversations$/);
    if (create) {
      if (failCreation) return route.fulfill({ status: 503, json: { detail: 'test unavailable' } });
      const made = binding('created', null);
      projects.push(made);
      return route.fulfill({ status: 201, json: made });
    }
    const chat = path.match(/^\/projects\/([^/]+)\/conversation$/);
    if (chat) {
      const body = request.method() === 'POST' ? request.postDataJSON() : null;
      const id = body?.conversation_id ?? url.searchParams.get('conversation_id');
      if (body?.confirmation) selection = body.confirmation;
      if (body && !body.confirmation) {
        messages.set(id, [{ id: body.message_id, role: 'user', agent: null, text: body.text, at: now }]);
        const project = projects.find((item) => item.project_id === chat[1]);
        project.title ||= body.text;
      }
      return route.fulfill({ status: body ? 202 : 200, json: { conversation_id: id, revision: selection && id === 'thread-saved' ? 2 : messages.has(id) ? 1 : 0,
        status: 'idle', messages: messages.get(id) ?? [], artifacts: id === 'thread-saved' ? [{ ...card, status: selection ? 'confirmed' : card.status }] : [], error: null } });
    }
    if (/\/runs$/.test(path)) return route.fulfill({ json: [] });
    if (path === '/ledger/hops') return route.fulfill({ json: { hops: [], latest_id: 0 } });
    if (path === '/ledger/hops/stream') return route.fulfill({ status: 200, contentType: 'text/event-stream', body: ': ready\n\n' });
    if (path === '/agents') return route.fulfill({ json: [] });
    return route.fulfill({ status: 404, json: { detail: 'Not needed by sidebar fixture' } });
  });
  try {
    const page = await context.newPage();
    const exceptions = [];
    page.on('pageerror', (error) => exceptions.push(error.message));
    await page.goto(`${baseUrl(byId('editor'))}/dwg`);
    const history = page.getByRole('navigation', { name: '저장된 대화' });
    await history.getByRole('button', { name: '저장된 어린이집 대화', exact: true }).click();
    await page.getByText('저장된 대화 내용입니다.', { exact: true }).waitFor();
    await page.getByRole('button', { name: '\uC774 \uC548 \uC120\uD0DD', exact: true }).click();
    await page.getByRole('button', { name: '\uC774 \uC548 \uC120\uD0DD', exact: true }).waitFor({ state: 'hidden' });
    assert.deepEqual(selection, { artifact_id: card.id, context_hash: card.data.context_hash });
    await page.getByRole('searchbox', { name: '대화 검색', exact: true }).fill('없는 검색어');
    await page.getByText('검색한 대화가 없어요.', { exact: true }).waitFor();
    await page.getByRole('searchbox', { name: '대화 검색', exact: true }).fill('');
    await page.getByRole('button', { name: '새 대화', exact: true }).click();
    await history.getByRole('button', { name: '새 대화', exact: true }).waitFor();
    await page.getByRole('textbox', { name: '메시지', exact: true }).fill('새 도서관 설계');
    await page.getByRole('button', { name: '보내기', exact: true }).click();
    await history.getByRole('button', { name: '새 도서관 설계', exact: true }).waitFor();
    await page.evaluate(() => localStorage.clear());
    await page.reload();
    await history.getByRole('button', { name: '새 도서관 설계', exact: true }).click();
    await page.locator('.agent-turn-user').filter({ hasText: '새 도서관 설계' }).waitFor();
    failCreation = true;
    await page.getByRole('button', { name: '새 대화', exact: true }).click();
    await page.getByText('새 대화를 만들지 못했어요. 다시 시도해 주세요.', { exact: true }).waitFor();
    assert.equal(await history.locator('[aria-current="page"]').innerText(), '새 도서관 설계');
    await page.locator('.sidebar-cad-module > summary').click();
    await page.getByRole('tab', { name: '프로젝트', exact: true }).waitFor();
    await page.getByRole('tab', { name: '세션', exact: true }).click();
    await page.locator('.sidebar-cad-module > summary').click();
    await history.getByRole('button', { name: '저장된 어린이집 대화', exact: true }).click();
    await page.locator('.sidebar-cad-module > summary').click();
    assert.equal(await page.getByRole('tab', { name: '세션', exact: true }).getAttribute('aria-selected'), 'true');
    await page.getByRole('button', { name: 'CAD 작업 열기', exact: true }).click();
    await page.locator('.dwg-conversation').waitFor();
    await history.getByRole('button', { name: '저장된 어린이집 대화', exact: true }).click();
    await page.getByText('저장된 대화 내용입니다.', { exact: true }).waitFor();
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole('button', { name: /탐색.*열기|메뉴|탐색 펼치기/ }).first().click();
    await page.getByRole('dialog', { name: '작업 탐색' }).waitFor();
    await history.getByRole('button', { name: '새 도서관 설계', exact: true }).click();
    await page.getByRole('dialog', { name: '작업 탐색' }).waitFor({ state: 'hidden' });
    await page.locator('.agent-turn-user').filter({ hasText: '새 도서관 설계' }).waitFor();
    assert.deepEqual(exceptions, []);
  } finally {
    await context.close();
    await browser.close();
  }
});
