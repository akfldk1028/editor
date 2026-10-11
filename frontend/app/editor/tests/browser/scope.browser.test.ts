import { after as afterAll, afterEach, before as beforeAll, beforeEach, test } from 'node:test'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { chromium, expect, type Browser, type Page } from '@playwright/test'
import type {} from './scope.browser-fixture'

let browser: Browser
let page: Page
let script: string
beforeAll(async () => {
  script = execFileSync(process.env.BUN_EXECUTABLE || 'bun', ['build', fileURLToPath(new URL('./scope.browser-fixture.tsx', import.meta.url)), '--tsconfig-override', fileURLToPath(new URL('../../tsconfig.json', import.meta.url)), '--target=browser', '--format=iife', '--define', 'process.env.NODE_ENV="development"', '--define', 'process.env.NEXT_PUBLIC_BASE_PATH=""'], { encoding: 'utf8', maxBuffer: 5_000_000 })
  browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_BROWSER_CHANNEL })
}, { timeout: 20000 })
beforeEach(async () => {
  page = await browser.newPage()
  page.on('pageerror', (error) => { console.error(error.message) })
  await page.setContent('<div id="root"></div>')
  await page.addScriptTag({ content: script })
  await page.waitForFunction(() => window.conversationScopeHarness.state().chosen === 'a')
}, { timeout: 20000 })
afterEach(async () => { await page?.close() })
afterAll(async () => { await browser?.close() })

test('mounted site switches project without poll or context ownership leaking', async () => {
  await page.evaluate(() => window.conversationScopeHarness.start())
  await page.waitForFunction(() => window.conversationScopeHarness.state().phase === 'submitted')
  await page.evaluate(() => window.conversationScopeHarness.switchProject('b'))
  expect(await page.evaluate(() => window.conversationScopeHarness.state())).toEqual({ chosen: 'b', phase: 'idle' })
  expect(await page.evaluate(() => window.conversationScopeHarness.context('b'))).toEqual({})
  await page.waitForTimeout(1100)
  expect(await page.evaluate(() => window.conversationScopeHarness.requests().some((url) => url.includes('run-a') && url.includes('project_id=b')))).toBe(false)
})

test('first Law run records context and follows shared project changes', async () => {
  await page.evaluate(() => window.conversationScopeHarness.mount('review'))
  await page.waitForFunction(() => window.conversationScopeHarness.state().phase === 'empty')
  await page.evaluate(() => window.conversationScopeHarness.start())
  await page.waitForFunction(() => window.conversationScopeHarness.context('a').law_run_id === 'run-a')
  expect(await page.evaluate(() => window.conversationScopeHarness.context('a').pnu)).toBe('parcel-a')
  await page.evaluate(() => window.conversationScopeHarness.setReviewDate('2026-10-10'))
  expect(await page.evaluate(() => window.conversationScopeHarness.context('a').assessment_date)).toBe('2026-10-10')
  expect(await page.evaluate(() => window.conversationScopeHarness.context('a').law_run_id)).toBeUndefined()
  await page.evaluate(() => window.conversationScopeHarness.switchProject('b'))
  await page.waitForFunction(() => window.conversationScopeHarness.state().phase === 'empty')
  expect(await page.evaluate(() => window.conversationScopeHarness.state().chosen)).toBe('b')
  expect(await page.evaluate(() => window.conversationScopeHarness.context('b'))).toEqual({})
})

test('disabled analysis resolves its site without starting a second agent request', async () => {
  await page.evaluate(() => window.conversationScopeHarness.mount('direct'))
  await page.evaluate(() => window.conversationScopeHarness.rerun())
  expect(await page.evaluate(() => window.conversationScopeHarness.requests().filter((url) => url.endsWith('/law-analysis')))).toHaveLength(0)
  await page.evaluate(() => window.conversationScopeHarness.enable(true))
  await page.waitForFunction(() => window.conversationScopeHarness.requests().some((url) => url.endsWith('/law-analysis')))
})

test('first site save binds its minimal prompt before the sole project mounts', async () => {
  const value = await page.evaluate(() => window.conversationScopeHarness.firstSelection())
  expect(value.selected.projectId).toBe('a')
  const actions = value.entries.find((entry) => entry.kind === 'prompt')?.actions
  expect(actions?.map((action) => action.label)).toEqual(['설계 시작하기', '법규 검토'])
  expect(actions?.[0]?.command?.kind).toBe('compose')
  expect(await page.evaluate(() => window.conversationScopeHarness.context('a').pnu)).toBe('parcel-a')
})
