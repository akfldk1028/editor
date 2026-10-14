import { afterEach, expect, test } from 'bun:test'
import { ConversationController } from './controller'
import { parseConversation } from './client'
import { confirmationFor } from './confirmation'
import { addProject, currentProjects } from './projects'
import type { ConversationSnapshot, ConversationSubmission } from './types'

const snapshot = (revision = 0, status: ConversationSnapshot['status'] = 'idle'): ConversationSnapshot => ({ conversation_id: 'main', revision, status, messages: [], artifacts: [], error: null })
const deferred = <T>() => { let resolve!: (value: T) => void; let reject!: (error: Error) => void; const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no }); return { promise, resolve, reject } }
const controllers: ConversationController[] = []
const create = (...args: ConstructorParameters<typeof ConversationController>) => { const result = new ConversationController(...args); controllers.push(result); return result }
const flush = () => new Promise((resolve) => setTimeout(resolve, 0))
async function until(check: () => boolean) { for (let n = 0; n < 100 && !check(); n++) await new Promise((resolve) => setTimeout(resolve, 2)); expect(check()).toBe(true) }
afterEach(() => { controllers.forEach((controller) => { controller.stop() }); controllers.length = 0 })

test('accepted ordinary messages update the sidebar title without a transient feed entry', async () => {
  addProject({ project_id: 'title-project', owner_project_id: 'owner', branch_id: 'c-title', scene_id: 's', scene_revision: 1,
    scene_project_id: null, conversation: true })
  const controller = create('title-project', 'main', { get: async () => snapshot(), post: async () => snapshot(1) })
  controller.start(); await flush(); controller.send('어린이집 설계', {}); await flush()
  expect(currentProjects().items.find((item) => item.project_id === 'title-project')?.title).toBe('어린이집 설계')
  controller.send('다음 질문', {}); await flush()
  expect(currentProjects().items.find((item) => item.project_id === 'title-project')?.title).toBe('어린이집 설계')
})

test('switching projects isolates late responses and retains dispatched work for returning to that project', async () => {
  const read = deferred<ConversationSnapshot>()
  const post = deferred<ConversationSnapshot>()
  let signal: AbortSignal | undefined
  const a = create('project-a', 'main', { get: async (_p, _c, s) => { signal = s; return read.promise }, post: async () => post.promise })
  a.start(); read.resolve(snapshot()); await flush()
  a.send('첫 프로젝트', {}); void a.refresh(); a.stop()
  const b = create('project-b', 'main', { get: async () => snapshot(7), post: async () => snapshot(8) })
  b.start(); post.resolve(snapshot(99)); await flush()
  expect(signal?.aborted).toBe(true)
  expect(a.getSnapshot().snapshot?.revision).toBe(99)
  expect(b.getSnapshot().snapshot?.revision).toBe(7)
  a.start(); await flush()
  expect(a.getSnapshot().snapshot?.revision).toBe(99)
})

test('polls restored working conversations through progressive revisions and slows when idle', async () => {
  let calls = 0
  const controller = create('project', 'main', { get: async () => { calls++; return snapshot(calls, calls < 3 ? 'working' : 'idle') }, post: async () => snapshot() }, 2)
  controller.start()
  await until(() => controller.getSnapshot().snapshot?.status === 'idle')
  const count = calls
  await new Promise((resolve) => setTimeout(resolve, 10))
  expect(calls).toBe(count)
  expect(controller.getSnapshot().snapshot?.revision).toBe(3)
})

test('idle conversation refreshes changed artifact state and stops when inactive', async () => {
  let reads = 0
  let current = { ...snapshot(1), artifacts: [{ id: 'program.r1', owner: 'program', title: 'Program', data: {}, status: 'valid' }] }
  const controller = create('project', 'main', { get: async () => { reads++; return current }, post: async () => snapshot() }, 2, 15)
  controller.start(); await flush()
  current = { ...current, revision: 2, artifacts: [{ ...current.artifacts[0]!, status: 'stale' }] }
  await until(() => controller.getSnapshot().snapshot?.artifacts[0]?.status === 'stale')
  controller.stop()
  const stoppedAt = reads
  await new Promise((resolve) => setTimeout(resolve, 25))
  expect(reads).toBe(stoppedAt)
})

test('out-of-order read cannot roll back a newer accepted message', async () => {
  const late = deferred<ConversationSnapshot>()
  let reads = 0
  const sent: ConversationSubmission[] = []
  const post = deferred<ConversationSnapshot>()
  const controller = create('project', 'main', { get: async () => ++reads === 1 ? snapshot() : late.promise, post: async (_p, body) => { sent.push(body); return post.promise } })
  controller.start(); await flush(); controller.send('첫 번째', {}); void controller.refresh()
  post.resolve({ ...snapshot(5, 'working'), messages: sent.map((body) => ({ id: body.message_id, role: 'user', agent: null, text: body.text, at: new Date().toISOString() })) })
  await flush(); late.resolve(snapshot(1)); await flush()
  expect(controller.getSnapshot().snapshot?.revision).toBe(5)
  expect(controller.getSnapshot().pending).toHaveLength(0)
})

test('two messages queued during work dispatch exactly once in order after idle polls', async () => {
  let state = snapshot(1, 'working')
  const sent: ConversationSubmission[] = []
  const controller = create('queue-project', 'main', { get: async () => state, post: async (_project, body) => {
    sent.push(body)
    state = { ...state, revision: state.revision + 1, status: 'working', messages: [...state.messages, { id: body.message_id, role: 'user', agent: null, text: body.text, at: new Date().toISOString() }] }
    return state
  } }, 5)
  controller.start(); await flush(); controller.send('first', {}); controller.send('second', {})
  const queuedIds = controller.getSnapshot().pending.map((item) => item.body.message_id)
  expect(sent).toHaveLength(0)
  expect(controller.getSnapshot().pending.every((item) => item.delivery === 'waiting')).toBe(true)
  state = { ...state, revision: 2, status: 'idle' }
  await until(() => sent.length === 1)
  expect(sent[0]?.text).toBe('first')
  expect(controller.getSnapshot().pending[0]?.body.text).toBe('second')
  state = { ...state, revision: 4, status: 'idle' }
  await until(() => sent.length === 2)
  expect(sent.map((item) => item.message_id)).toEqual(queuedIds)
  expect(controller.getSnapshot().pending).toHaveLength(0)
  await new Promise((resolve) => setTimeout(resolve, 15))
  expect(sent).toHaveLength(2)
})

test('transport failure blocks queue until explicit retry, including across project suspension', async () => {
  const sent: ConversationSubmission[] = []
  let state = snapshot()
  const controller = create('failed-queue', 'main', { get: async () => state, post: async (_project, body) => {
    sent.push(body)
    if (sent.length === 1) throw new Error('offline')
    state = { ...state, revision: state.revision + 1, messages: [...state.messages, { id: body.message_id, role: 'user', agent: null, text: body.text, at: new Date().toISOString() }] }
    return state
  } }, 5)
  controller.start(); await flush(); controller.send('first', {}); controller.send('second', {}); await flush()
  controller.stop(); controller.start(); await flush()
  await new Promise((resolve) => setTimeout(resolve, 15))
  expect(sent).toHaveLength(1)
  expect(controller.getSnapshot().pending).toHaveLength(2)
  controller.retry(sent[0]!.message_id)
  await until(() => sent.length === 3)
  expect(sent[1]).toEqual(sent[0])
  expect(sent[2]?.text).toBe('second')
})

test('uncertain POST failures retry identical id and context, then reconcile without duplicates', async () => {
  const sent: ConversationSubmission[] = []
  const controller = create('project', 'main', { get: async () => snapshot(), post: async (_p, body) => {
    sent.push(body)
    if (sent.length === 1) throw new Error('connection lost')
    return { ...snapshot(1, 'working'), messages: [{ id: body.message_id, role: 'user', agent: null, text: body.text, at: new Date().toISOString() }] }
  } })
  controller.start(); await flush(); controller.send('바꾸기', { pnu: '123', address: '선택 대지' }); await flush()
  expect(controller.getSnapshot().pending[0]?.error).toBe('connection lost')
  controller.retry(sent[0]!.message_id); await flush()
  expect(sent[1]).toEqual(sent[0])
  expect(controller.getSnapshot().pending).toHaveLength(0)
})

test('poll connection error retains saved messages and recovers', async () => {
  let calls = 0
  const controller = create('project', 'main', { get: async () => { calls++; if (calls === 2) throw new Error('offline'); return snapshot(calls, calls < 3 ? 'working' : 'idle') }, post: async () => snapshot() }, 15)
  controller.start(); await until(() => controller.getSnapshot().error === 'offline')
  expect(controller.getSnapshot().snapshot?.revision).toBe(1)
  await until(() => controller.getSnapshot().snapshot?.revision === 3)
  expect(controller.getSnapshot().error).toBeNull()
})

test('contract accepts arbitrary owner and artifact data but rejects malformed responses', () => {
  const value = { ...snapshot(), artifacts: [{ id: 'result', owner: 'new-specialist', title: '새 결과', status: 'ready', data: { spaces: ['작업실'] } }] }
  expect(parseConversation(value)).toEqual(value)
  expect(() => parseConversation({ ...value, revision: -1 })).toThrow()
  expect(() => parseConversation({ ...value, artifacts: [{ ...value.artifacts[0], data: [] }] })).toThrow()
})

const reconfirmation = { id: 'intent-review', owner: 'orchestrator', title: '설계 의도 재확인', status: 'awaiting_confirmation', data: { kind: 'intent_reconfirmation', context_hash: 'a'.repeat(64), context: { nodes: {} }, proposed_intent: { description: '검토할 설계 의도' } } }

test('only explicit server reconfirmation artifacts offer confirmation', () => {
  expect(confirmationFor(reconfirmation)).toEqual({ artifact_id: 'intent-review', context_hash: 'a'.repeat(64) })
  expect(confirmationFor({ ...reconfirmation, status: 'proposal' })).toBeUndefined()
  expect(confirmationFor({ ...reconfirmation, data: { ...reconfirmation.data, kind: 'intent_proposal' } })).toBeUndefined()
  expect(confirmationFor({ ...reconfirmation, data: { ...reconfirmation.data, context_hash: 'invalid' } })).toBeUndefined()
})

test('confirmation binds to current artifact version and retries its identical explicit reference', async () => {
  const sent: ConversationSubmission[] = []
  const state = { ...snapshot(2), artifacts: [reconfirmation] }
  const controller = create('confirmation-project', 'main', { get: async () => state, post: async (_project, body) => { sent.push(body); throw new Error('offline') } })
  controller.start(); await flush()
  controller.confirm({ ...reconfirmation, data: { ...reconfirmation.data, context_hash: 'b'.repeat(64) } })
  controller.confirm({ ...reconfirmation, id: 'another-artifact' })
  expect(sent).toHaveLength(0)
  controller.confirm(reconfirmation); await flush()
  expect(sent[0]?.confirmation).toEqual({ artifact_id: 'intent-review', context_hash: 'a'.repeat(64) })
  expect(sent[0]?.text).toBe('변경된 조건을 기준으로 이 설계 의도를 확인합니다.')
  controller.confirm(reconfirmation)
  expect(sent).toHaveLength(1)
  controller.retry(sent[0]!.message_id); await flush()
  expect(sent[1]).toEqual(sent[0])
})

test('working conversation cannot dispatch an intent confirmation', async () => {
  let calls = 0
  const controller = create('working-project', 'main', { get: async () => ({ ...snapshot(2, 'working'), artifacts: [reconfirmation] }), post: async () => { calls++; return snapshot(3) } })
  controller.start(); await flush(); controller.confirm(reconfirmation)
  expect(calls).toBe(0)
})


test('explicit discard releases a rejected message without resending it', async () => {
  const sent: ConversationSubmission[] = []
  const controller = create('discard', 'main', { get: async () => snapshot(), post: async (_p, body) => {
    sent.push(body)
    if (sent.length === 1) throw new Error('stale confirmation')
    return { ...snapshot(1), messages: [{ id: body.message_id, role: 'user', agent: null, text: body.text, at: new Date().toISOString() }] }
  } })
  controller.start(); await flush(); controller.send('stale', {}); controller.send('next', {}); await flush()
  controller.discard(sent[0]!.message_id)
  await until(() => sent.length === 2)
  expect(sent.map((body) => body.text)).toEqual(['stale', 'next'])
  expect(controller.getSnapshot().pending).toHaveLength(0)
})

test('a message the editor located leaves the pending queue and reaches onLocated without touching the snapshot', async () => {
  const located = { kind: 'site' as const, query: '산곡동 684-1', pnu: '4115011300106840001', address: '경기도 의정부시 산곡동 684-1', coordinates: { x: 127.1, y: 37.7 }, error: null }
  const sent: ConversationSubmission[] = []
  // The owner's snapshot records the message it took (its id confirms the pending one), as the real door does.
  const taken = (revision: number, body: ConversationSubmission) => ({ ...snapshot(revision), messages: [{ id: body.message_id, role: 'user' as const, agent: null, text: body.text, at: '2026-10-12T00:00:00Z' }] })
  const controller = create('project', 'main', { get: async () => snapshot(3), post: async (_p, body) => { sent.push(body); return body.text === '산곡동 684-1' ? { located } : body.text.includes('684-1에') ? { ...taken(4, body), located } : taken(5, body) } })
  const heard: [unknown, string | null][] = []
  controller.onLocated = (body, text) => { heard.push([body, text]) }
  controller.start(); await flush()
  controller.send('산곡동 684-1', { assessment_date: '2026-10-06' })
  await until(() => heard.length === 1)
  expect(heard[0]).toEqual([located, '산곡동 684-1'])
  expect(controller.getSnapshot().pending).toEqual([])
  expect(controller.getSnapshot().snapshot?.revision).toBe(3)
  // A sentence naming the site: the owner keeps the message (snapshot accepted) and the map still moves (text null).
  controller.send('산곡동 684-1에 어린이집', {})
  await until(() => heard.length === 2)
  expect(heard[1]).toEqual([located, null])
  expect(controller.getSnapshot().snapshot?.revision).toBe(4)
  expect(controller.getSnapshot().snapshot).not.toHaveProperty('located')
  controller.send('그 땅에 어린이집', {})
  await until(() => controller.getSnapshot().snapshot?.revision === 5)
  expect(sent.map((body) => body.text)).toEqual(['산곡동 684-1', '산곡동 684-1에 어린이집', '그 땅에 어린이집'])
  expect(heard.length).toBe(2)
})
