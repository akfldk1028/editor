import { expect, test } from 'bun:test'

import type { ProjectBinding } from '../../../agent-dialogue/projects'
import { RunRequestError } from '../../../agent-dialogue/runs'
import type { SavedSite } from './picks'
import { bundleNotice, describeFailure, idempotencyKey, isTerminal, resolveProject, runNotice, siteRunRequest, statusLabel, traceLabel, LAYOUT_STORAGE_KEY, layoutBlocker, layoutRunRequest, loadLayoutInputs, massRunRequest, saveLayoutInputs } from './site-run'

const binding = (project_id: string): ProjectBinding =>
  ({ project_id, owner_project_id: 'owner-' + project_id, branch_id: 'main', scene_id: 's', scene_revision: 1, scene_project_id: null })

const parcel = (pnu: string, address: string) =>
  ({ pnu, address, lng: 127, lat: 37, summary: { address, land_category: null, area_m2: null, zones: [] } })

const site = (...parcels: ReturnType<typeof parcel>[]): SavedSite => ({
  selection_id: '91dccc4b-e120-4925-82a2-339f3ac0c054', created_at: '', parcel_count: parcels.length,
  label: parcels[0]!.address, parcels, total_area_m2: null, contiguous: true, zones: [],
})

const conditions = { assessmentDate: '2026-10-08', buildingType: '' }

test('the project is ?project= when bound, else the only binding, else a choice or none', () => {
  const [a, b] = [binding('a'), binding('b')]
  expect(resolveProject([a, b], 'b')).toEqual({ kind: 'resolved', project: b })
  expect(resolveProject([a], 'missing')).toEqual({ kind: 'resolved', project: a })
  expect(resolveProject([a, b], undefined)).toEqual({ kind: 'choose', projects: [a, b] })
  const none = resolveProject([], 'a')
  expect(none.kind).toBe('none')
  if (none.kind === 'none') expect(none.reason).toContain('프로젝트가 없어요')
})

test('a site run sends the whole bundle led by its first parcel, the 기준일, and the 용도 only when chosen', () => {
  const one = site(parcel('4115011300106840001', '경기도 의정부시 산곡동 684-1'))
  expect(siteRunRequest(one, conditions)).toEqual({ goal: 'limits', pnu: '4115011300106840001', parcels: ['4115011300106840001'], assessment_date: '2026-10-08' })
  const two = site(parcel('4115011300106840001', '경기도 의정부시 산곡동 684-1'), parcel('4115011300106840003', '경기도 의정부시 산곡동 684-3'))
  expect(siteRunRequest(two, { ...conditions, buildingType: ' 업무시설 ' })).toEqual({
    goal: 'limits', pnu: '4115011300106840001', parcels: ['4115011300106840001', '4115011300106840003'],
    assessment_date: '2026-10-08', building_type: '업무시설',
  })
})

test('a 배치 설계 request carries the bundle, the 용도, the floor area, the footprint wanted and the intent exactly as typed', () => {
  const inputs = { floorAreaM2: '3,000', footprintM2: '600', intent: ' 1층은 상가로 열고, 외장은 커튼월로 ', parkingStalls: '', maxSurfaceStalls: '' }
  const bare = { parkingStalls: '', maxSurfaceStalls: '' }
  expect(layoutRunRequest(site(parcel('4115011300106840001', '산곡동 684-1')), { assessmentDate: '2026-10-16', buildingType: '제2종근린생활시설' }, inputs)).toEqual({
    goal: 'masterplan', pnu: '4115011300106840001', parcels: ['4115011300106840001'], assessment_date: '2026-10-16',
    building_type: '제2종근린생활시설', floor_area_m2: 3000, footprint_m2: 600, intent: '1층은 상가로 열고, 외장은 커튼월로',
  })
  expect(layoutRunRequest(site(parcel('4115011300106840001', 'x')), { assessmentDate: '2026-10-16', buildingType: '업무시설' }, { floorAreaM2: '500', footprintM2: '100', intent: '   ', ...bare })).not.toHaveProperty('intent')
  // what blocks the button, in Korean: no 용도, a floor area or footprint that is not a number, a footprint above the floor area, an intent too long
  expect(layoutBlocker({ assessmentDate: '2026-10-16', buildingType: '' }, inputs)).toMatch(/용도/)
  expect(layoutBlocker({ assessmentDate: '2026-10-16', buildingType: '업무시설' }, { floorAreaM2: 'abc', footprintM2: '5', intent: '', ...bare })).toMatch(/연면적/)
  expect(layoutBlocker({ assessmentDate: '2026-10-16', buildingType: '업무시설' }, { floorAreaM2: '10', footprintM2: '', intent: '', ...bare })).toMatch(/바닥면적/)
  expect(layoutBlocker({ assessmentDate: '2026-10-16', buildingType: '업무시설' }, { floorAreaM2: '10', footprintM2: '20', intent: '', ...bare })).toMatch(/연면적보다/)
  expect(layoutBlocker({ assessmentDate: '2026-10-16', buildingType: '업무시설' }, { floorAreaM2: '10', footprintM2: '10', intent: 'x'.repeat(2001), ...bare })).toMatch(/2,000/)
  expect(layoutBlocker({ assessmentDate: '2026-10-16', buildingType: '업무시설' }, { floorAreaM2: '10', footprintM2: '4', intent: '', ...bare })).toBeNull()
  // the inputs round-trip through storage; junk falls back to empty fields
  const map = new Map<string, string>()
  const store = { getItem: (key: string) => map.get(key) ?? null, setItem: (key: string, value: string) => void map.set(key, value) }
  saveLayoutInputs(inputs, store)
  expect(loadLayoutInputs(store)).toEqual(inputs)
  store.setItem(LAYOUT_STORAGE_KEY, '{"floorAreaM2": 3, "intent": null}')
  expect(loadLayoutInputs(store)).toEqual({ floorAreaM2: '', footprintM2: '', intent: '', ...bare })
})

test('the parking planned rides on a 배치 설계 (so a basement and ramp are planned), never on a 매스 설계', () => {
  const where = site(parcel('4115011300106840001', 'x'))
  const when = { assessmentDate: '2026-10-22', buildingType: '업무시설' }
  const inputs = { floorAreaM2: '3,926', footprintM2: '1074', intent: '', parkingStalls: '50', maxSurfaceStalls: '30' }
  expect(layoutRunRequest(where, when, inputs)).toMatchObject({ parking_stalls: 50, max_surface_stalls: 30 })
  expect(massRunRequest(where, when, inputs)).not.toHaveProperty('parking_stalls')
  expect(massRunRequest(where, when, inputs)).not.toHaveProperty('max_surface_stalls')
  expect(layoutRunRequest(where, when, { ...inputs, parkingStalls: '', maxSurfaceStalls: '' })).not.toHaveProperty('parking_stalls')
  expect(layoutBlocker(when, { ...inputs, parkingStalls: '50.5' })).toMatch(/정수/)
  expect(layoutBlocker(when, { ...inputs, parkingStalls: '20' })).toMatch(/클 수 없어요/)
  expect(layoutBlocker(when, { ...inputs, parkingStalls: '' })).toMatch(/주차 대수도/)
  expect(layoutBlocker(when, inputs)).toBeNull()
})

test('only a bundle the map found not touching gets a notice', () => {
  const two = site(parcel('4115011300106840001', ''), parcel('4115011300106840003', ''))
  expect(bundleNotice(two)).toBeNull()
  expect(bundleNotice({ ...two, contiguous: null })).toBeNull()
  expect(bundleNotice({ ...two, contiguous: false })).toBe('서로 붙어 있지 않은 묶음은 합필 검토가 거절돼요 (parcels_not_contiguous)')
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
  expect(isTerminal('blocked')).toBe(true)
  expect(statusLabel('queued')).toBe('대기')
  expect(statusLabel('running')).toBe('진행 중')
  expect(statusLabel('completed')).toBe('완료')
  expect(statusLabel('blocked')).toBe('보류 — 근거 보충 필요')
  expect(statusLabel('failed')).toBe('실패')
  expect(statusLabel('odd')).toBe('odd')
})

test('a finished run whose site_resolve failed on parcels_not_contiguous says so in Korean; open or other runs say nothing', () => {
  const comm = (state: string, response_text: string | null) =>
    ({ id: 'c', task_id: 'site_resolve', tool: 'site_resolve', agent: 'site_context', state, request_text: null, response_text, transport: 'a2a' as const, truncated: false })
  const apart = comm('failed', '{"status": "failed", "code": "parcels_not_contiguous", "error": "the parcels do not form one contiguous site"}')
  expect(runNotice({ status: 'failed', communications: [apart] })).toBe('필지가 서로 붙어 있지 않아 합필 검토가 거절됐어요')
  expect(runNotice({ status: 'running', communications: [apart] })).toBeNull()
  expect(runNotice({ status: 'failed', communications: [comm('failed', null), comm('succeeded', 'parcels_not_contiguous')] })).toBeNull()
  expect(runNotice({ status: 'blocked', communications: [] })).toBeNull()
})

test('503 and a dropped connection mean the Orchestrator is off; 4xx carries the reason in Korean', () => {
  expect(describeFailure(new RunRequestError('x', 503, 'external_outcome_unknown'))).toEqual({ kind: 'unavailable' })
  expect(describeFailure(new TypeError('Failed to fetch'))).toEqual({ kind: 'unavailable' })
  const conflict = describeFailure(new RunRequestError('x', 409, 'Request identity or source version conflict'))
  expect(conflict.kind).toBe('rejected')
  if (conflict.kind === 'rejected') expect(conflict.text).toBe('요청이 충돌했어요 (409) — 같은 키로 다른 내용이 접수됐거나 장면·원본 버전이 바뀌었어요. 다시 시도하면 새 키로 보내요.')
  const apart = describeFailure(new RunRequestError('x', 409, 'Site refused the bundle: parcels_not_contiguous'))
  if (apart.kind === 'rejected') expect(apart.text).toBe('필지가 서로 붙어 있지 않아 합필 검토가 거절됐어요 (409)')
  const bad = describeFailure(new RunRequestError('x', 422, null))
  if (bad.kind === 'rejected') expect(bad.text).toBe('요청이 거절됐어요 (422) — x')
})
