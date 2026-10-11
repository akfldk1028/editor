import { afterEach, expect, spyOn, test } from 'bun:test'
import { GET, POST } from '../../app/api/v1/platform/[...path]/route'
import { getConversation, postConversation } from './client'

let fetchSpy: ReturnType<typeof spyOn> | undefined
const oldBackend = process.env.EDITOR_BACKEND_URL
afterEach(() => { fetchSpy?.mockRestore(); if (oldBackend === undefined) delete process.env.EDITOR_BACKEND_URL; else process.env.EDITOR_BACKEND_URL = oldBackend })
const body = { conversation_id: 'main', message_id: 'message-1', text: '요청', context: { address: '대지' } }
const answer = { conversation_id: 'main', revision: 1, status: 'working', messages: [], artifacts: [], error: null }

test('client sends stable message body and refreshes explicit conversation without cache', async () => {
  const calls: { url: string; init?: RequestInit }[] = []
  fetchSpy = spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => { calls.push({ url: String(url), init }); return Response.json(answer, { status: 202 }) })
  await postConversation('project-1', body); await getConversation('project-1', 'draft.2')
  expect(calls[0]?.url).toEndWith('/api/v1/platform/projects/project-1/conversation')
  expect(JSON.parse(String(calls[0]?.init?.body))).toEqual(body)
  expect(calls[0]?.init?.signal).toBeUndefined()
  expect(calls[1]?.url).toEndWith('/conversation?conversation_id=draft.2')
  expect(calls[1]?.init?.cache).toBe('no-store')
})

test('platform proxy forwards conversation GET/POST and query, rejects extra paths', async () => {
  process.env.EDITOR_BACKEND_URL = 'http://backend.test'
  const urls: string[] = []
  fetchSpy = spyOn(globalThis, 'fetch').mockImplementation(async (url) => { urls.push(String(url)); return Response.json(answer) })
  const context = { params: Promise.resolve({ path: ['projects', 'project-1', 'conversation'] }) }
  expect((await GET(new Request('http://editor.test/api/v1/platform/projects/project-1/conversation?conversation_id=main'), context)).status).toBe(200)
  expect(urls[0]).toContain('conversation?conversation_id=main')
  expect((await POST(new Request('http://editor.test/api/v1/platform/projects/project-1/conversation', { method: 'POST', headers: { Origin: 'http://editor.test', 'Content-Type': 'application/json' }, body: JSON.stringify(body) }), context)).status).toBe(200)
  expect((await GET(new Request('http://editor.test/api/v1/platform/projects/project-1/conversation/delete'), { params: Promise.resolve({ path: ['projects', 'project-1', 'conversation', 'delete'] }) })).status).toBe(404)
})
