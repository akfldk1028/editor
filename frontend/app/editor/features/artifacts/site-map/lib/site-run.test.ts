import { expect, test } from 'bun:test'

import type { ProjectBinding } from '../../../agent-dialogue/projects'
import { RunRequestError } from '../../../agent-dialogue/runs'
import type { SavedSite } from './picks'
import { bundleNotice, describeFailure, idempotencyKey, isTerminal, resolveProject, siteRunRequest, statusLabel, traceLabel } from './site-run'

const binding = (project_id: string): ProjectBinding =>
  ({ project_id, owner_project_id: 'owner-' + project_id, branch_id: 'main', scene_id: 's', scene_revision: 1, scene_project_id: null })

const parcel = (pnu: string, address: string) =>
  ({ pnu, address, lng: 127, lat: 37, summary: { address, land_category: null, area_m2: null, zones: [] } })

const site = (...parcels: ReturnType<typeof parcel>[]): SavedSite => ({
  selection_id: '91dccc4b-e120-4925-82a2-339f3ac0c054', created_at: '', parcel_count: parcels.length,
  label: parcels[0]!.address, parcels, total_area_m2: null, contiguous: true, zones: [],
})

test('the project is ?project= when bound, else the only binding, else a choice or none', () => {
  const [a, b] = [binding('a'), binding('b')]
  expect(resolveProject([a, b], 'b')).toEqual({ kind: 'resolved', project: b })
  expect(resolveProject([a], 'missing')).toEqual({ kind: 'resolved', project: a })
  expect(resolveProject([a, b], undefined)).toEqual({ kind: 'choose', projects: [a, b] })
  const none = resolveProject([], 'a')
  expect(none.kind).toBe('none')
  if (none.kind === 'none') expect(none.reason).toContain('프로젝트가 없어요')
})

test('a site run sends goal limits with the first parcel only, and says so for a bundle', () => {
  const one = site(parcel('4115011300106840001', '경기도 의정부시 산곡동 684-1'))
  expect(siteRunRequest(one)).toEqual({ goal: 'limits', pnu: '4115011300106840001' })
  expect(bundleNotice(one)).toBeNull()
  const two = site(parcel('4115011300106840001', '경기도 의정부시 산곡동 684-1'), parcel('4115011300106850000', '경기도 의정부시 산곡동 685'))
  expect(siteRunRequest(two)).toEqual({ goal: 'limits', pnu: '4115011300106840001' })
  expect(bundleNotice(two)).toBe('지금은 첫 필지(684-1)만 오케스트레이터에 보내요 — 여러 필지 지원은 준비 중')
})

test('each attempt gets its own header-safe idempotency key', () => {
  const one = site(parcel('4115011300106840001', ''))
  expect(idempotencyKey(one, 1)).toBe('site-91dccc4b-e120-4925-82a2-339f3ac0c054-1')
  expect(idempotencyKey(one, 2)).not.toBe(idempotencyKey(one, 1))
  expect(idempotencyKey({ ...one, selection_id: 'a b/c' }, 3)).toMatch(/^[A-Za-z0-9_-]{1,128}$/)
})

test('the trace label is the first 8 hex of the W3C trace id', () => {
  expect(traceLabel('4bf92f3577b34da6a3ce929d0e0e4736')).toBe('4bf92f35')
})

test('statuses: queued/running/queued_input stay open, the rest end, labels are Korean', () => {
  expect(isTerminal('queued')).toBe(false)
  expect(isTerminal('running')).toBe(false)
  expect(isTerminal('queued_input')).toBe(false)
  expect(isTerminal('completed')).toBe(true)
  expect(isTerminal('failed')).toBe(true)
  expect(statusLabel('queued')).toBe('대기')
  expect(statusLabel('running')).toBe('진행 중')
  expect(statusLabel('completed')).toBe('완료')
  expect(statusLabel('failed')).toBe('실패')
  expect(statusLabel('odd')).toBe('odd')
})

test('503 and a dropped connection mean the Orchestrator is off; 4xx carries the reason in Korean', () => {
  expect(describeFailure(new RunRequestError('x', 503, 'external_outcome_unknown'))).toEqual({ kind: 'unavailable' })
  expect(describeFailure(new TypeError('Failed to fetch'))).toEqual({ kind: 'unavailable' })
  const conflict = describeFailure(new RunRequestError('x', 409, 'Request identity or source version conflict'))
  expect(conflict.kind).toBe('rejected')
  if (conflict.kind === 'rejected') expect(conflict.text).toBe('요청이 충돌했어요 (409) — 같은 키로 다른 내용이 접수됐거나 장면·원본 버전이 바뀌었어요. 다시 시도하면 새 키로 보내요.')
  const bad = describeFailure(new RunRequestError('x', 422, null))
  if (bad.kind === 'rejected') expect(bad.text).toBe('요청이 거절됐어요 (422) — x')
})
