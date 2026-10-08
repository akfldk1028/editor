import { expect, test } from 'bun:test'

import type { ServiceStatus } from '../api/status'
import { downHint, formatClock, formatUptime, groupServices, summarize } from './presentation'

const row = (id: string, kind: ServiceStatus['kind'], state: ServiceStatus['state'], management = 'agent-host'): ServiceStatus => ({
  id, kind, label: id, port: 1, lifecycle: 'persistent', management, notes: '', state, http_status: null, version: null,
  started_at: null, latency_ms: null, checked_at: '2026-10-08T05:00:00Z', error: null, managed_by: null, orchestrator: null,
})

test('groups follow the sidebar order, keep registry order inside, and drop empty groups', () => {
  const groups = groupServices([row('law', 'agent', 'up'), row('backend', 'editor', 'up'), row('scene', 'agent', 'down'), row('hub', 'orchestrator', 'down')])
  expect(groups.map((group) => group.title)).toEqual(['에디터', '오케스트레이터', '에이전트'])
  expect(groups[2]!.rows.map((r) => r.id)).toEqual(['law', 'scene'])
  expect(groups[2]!.up).toBe(1)
})

test('uptime reads in Korean units and tolerates missing or bad stamps', () => {
  const now = Date.parse('2026-10-08T12:00:00Z')
  expect(formatUptime(null, now)).toBe('—')
  expect(formatUptime('garbage', now)).toBe('—')
  expect(formatUptime('2026-10-08T11:59:20Z', now)).toBe('40초')
  expect(formatUptime('2026-10-08T11:30:10Z', now)).toBe('29분 50초')
  expect(formatUptime('2026-10-08T09:30:00Z', now)).toBe('2시간 30분')
  expect(formatUptime('2026-10-05T10:00:00Z', now)).toBe('3일 2시간')
})

test('the clock says "n초 전" inside a minute and a wall-clock time after', () => {
  const now = Date.parse('2026-10-08T12:00:30Z')
  expect(formatClock('2026-10-08T12:00:25Z', now)).toBe('5초 전')
  expect(formatClock('2026-10-08T11:00:00Z', now)).toMatch(/^\d{2}:\d{2}:\d{2}$/)
  expect(formatClock(null, now)).toBe('—')
})

test('the summary counts only probed rows', () => {
  const status = { checked_at: '2026-10-08T12:00:00Z', orchestrator: { state: 'down' as const, error: null },
    services: [row('a', 'agent', 'up'), row('b', 'agent', 'down'), row('neo4j', 'infra', 'unknown')] }
  expect(summarize(status, Date.parse('2026-10-08T12:00:03Z'))).toBe('1/2 가동 · 3초 전 확인')
})

test('down hints name who turns the service back on', () => {
  expect(downHint(row('law', 'agent', 'up'))).toBeNull()
  expect(downHint(row('orchestrator', 'orchestrator', 'down'))).toContain('오케스트레이터가 필요해요')
  expect(downHint(row('backend', 'editor', 'down', 'editor-session'))).toContain('bun run host:start backend')
  expect(downHint(row('law', 'agent', 'down'))).toContain('에이전트 담당 세션')
  expect(downHint(row('neo4j', 'infra', 'unknown', 'external'))).toContain('Bolt')
})
