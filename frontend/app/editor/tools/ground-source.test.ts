import { expect, test } from 'bun:test'
import { groundSource, GroundSourceUnavailable } from './ground-source'

test('temporary restart retries the same cell and resumes after recovery', async () => {
  let calls = 0
  const delays: number[] = []
  const get = (async () => {
    if (++calls === 1) throw new TypeError('connection refused')
    return calls === 2 ? new Response('', { status: 503 }) : Response.json({ status: 'ok' })
  }) as typeof fetch
  expect((await groundSource('http://local/cell', get, async ms => { delays.push(ms) })).ok).toBe(true)
  expect(calls).toBe(3)
  expect(delays).toEqual([1000, 2000])
})

test('sustained outage stops the batch rather than exhausting unvisited cells', async () => {
  let calls = 0
  const get = (async () => { calls++; throw new TypeError('connection refused') }) as typeof fetch
  await expect(groundSource('http://local/cell', get, async () => {})).rejects.toBeInstanceOf(GroundSourceUnavailable)
  expect(calls).toBe(6)
})
