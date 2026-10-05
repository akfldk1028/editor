import { afterEach, expect, test } from 'bun:test'
import { ExecutionClient } from './execution-client'
const originalFetch = globalThis.fetch
afterEach(() => { globalThis.fetch = originalFetch })
const json = (value: unknown) => new Response(JSON.stringify(value))

test('resume drains all terminal pages using has_more without repeating start', async () => {
  const requests: string[] = []
  const received: number[] = []
  let done!: () => void
  const completion = new Promise<void>(resolve => { done = resolve })
  globalThis.fetch = (async (url) => {
    const path = String(url); requests.push(path)
    const base = { run_id: 'run1', session_id: 7, status: 'complete' }
    if (!path.includes('?')) return json({ ...base, events: [], has_more: false })
    if (path.endsWith('after=0')) return json({ ...base, events: [{ seq: 1, type: 'message', data: {} }], has_more: true })
    return json({ ...base, events: [{ seq: 2, type: 'completion' }], has_more: false })
  }) as typeof fetch
  const client = new ExecutionClient({ runId: 'run1', sessionId: 7, onMessage: value => received.push(value.seq!), onClose: done })
  await client.resume()
  await completion
  expect(received).toEqual([1, 2])
  expect(requests.some(url => url.endsWith('/start'))).toBe(false)
  expect(requests.at(-1)).toEndWith('after=1')
  client.disconnect()
})

test('session identity mismatch cannot attach a restored run to another session', async () => {
  globalThis.fetch = (async () => json({ run_id: 'run1', session_id: 9, events: [] })) as typeof fetch
  const client = new ExecutionClient({ runId: 'run1', sessionId: 7, onMessage: () => { throw new Error('unexpected event') } })
  await expect(client.resume()).rejects.toThrow('session mismatch')
  expect(client.isConnected).toBe(false)
})

test('disconnect aborts pending event transport and ignores a late result', async () => {
  let complete!: (response: Response) => void
  const events = new Promise<Response>(resolve => { complete = resolve })
  let signal: AbortSignal | null | undefined
  const messages: unknown[] = []
  globalThis.fetch = (async (url, init) => {
    if (!String(url).includes('?')) return json({ run_id: 'run1', session_id: 7, events: [] })
    signal = init?.signal
    return events
  }) as typeof fetch
  const client = new ExecutionClient({ runId: 'run1', onMessage: value => messages.push(value) })
  await client.resume()
  client.disconnect()
  expect(signal?.aborted).toBe(true)
  complete(json({ run_id: 'run1', events: [{ seq: 1, type: 'message' }], status: 'complete' }))
  await new Promise(resolve => setTimeout(resolve, 5))
  expect(messages).toEqual([])
})

test('failed input is not acknowledged or retried automatically', async () => {
  let posts = 0
  const errors: string[] = []
  globalThis.fetch = (async () => { posts++; return new Response('{}', { status: 503 }) }) as typeof fetch
  const client = new ExecutionClient({ runId: 'run1', onMessage: () => {}, onError: value => errors.push(value) })
  await expect(client.sendInput('answer')).rejects.toThrow('503')
  expect(posts).toBe(1)
  expect(errors).toHaveLength(1)
})
