import { expect, test } from 'bun:test'

import type { Communication } from '@/lib/orchestrator-runs/types'

import { ORCHESTRATOR, toTranscript } from './transcript'

const row = (over: Partial<Communication> = {}): Communication => ({
  id: 'c1', task_id: 'site_resolve', tool: 'site_resolve', agent: 'site_context', state: 'succeeded',
  request_text: '{"pnu":"1"}', response_text: '{"status":"partial"}', transport: 'a2a', truncated: false, ...over,
})
const run = (rows: Communication[], over = {}) => ({ communications: rows, communications_available: true, communications_truncated: false, ...over })

test('each recorded row becomes a request from the Orchestrator and, once answered, a response back', () => {
  const transcript = toTranscript(run([row(), row({ id: 'c2', tool: 'law_parcel_limits', agent: 'law', response_text: null })]))
  expect(transcript.participants).toEqual([ORCHESTRATOR, 'site_context', 'law'])
  expect(transcript.messages.map((m) => [m.direction, m.from, m.to, m.step])).toEqual([
    ['request', 'orchestrator', 'site_context', 1], ['response', 'site_context', 'orchestrator', 2], ['request', 'orchestrator', 'law', 3],
  ])
})

test('an agent alias resolves to its canonical id and a tool without an agent goes to the tool owner', () => {
  const transcript = toTranscript(run([row({ agent: 'site' }), row({ id: 'c2', tool: 'law_parcel_limits', agent: null })]))
  expect(transcript.participants).toEqual([ORCHESTRATOR, 'site_context', 'law'])
})

test('a cut record is flagged at the transcript and at the message', () => {
  const transcript = toTranscript(run([row({ truncated: true })]))
  expect(transcript.truncated).toBe(true)
  expect(transcript.messages.every((m) => m.truncated)).toBe(true)
  expect(toTranscript(run([], { communications_available: false })).available).toBe(false)
})
