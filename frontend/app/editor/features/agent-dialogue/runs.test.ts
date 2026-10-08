import { expect, test } from 'bun:test'

import { parseRun } from './runs'

const run = {
  run_id: 'r1',
  request_id: 'editor:p:k',
  owner_project_id: 'p',
  branch_id: 'main',
  goal: 'limits',
  status: 'queued',
  receipt_task_ids: [],
  pending_input: false,
}

test('parseRun keeps a well-formed trace_id and drops anything else in that slot', () => {
  const traced = parseRun({ ...run, trace_id: 'a'.repeat(32) })
  expect(traced.trace_id).toBe('a'.repeat(32))
  expect(traced.run_id).toBe('r1')
  expect('trace_id' in parseRun(run)).toBe(false)
  expect('trace_id' in parseRun({ ...run, trace_id: 7 })).toBe(false)
  expect('trace_id' in parseRun({ ...run, trace_id: 'short' })).toBe(false)
})

test('parseRun still rejects a run that is not a run', () => {
  expect(() => parseRun({ ...run, run_id: 1 })).toThrow('실행 응답 형식이 올바르지 않습니다.')
  expect(() => parseRun(null)).toThrow()
})
