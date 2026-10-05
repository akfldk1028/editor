import { afterEach, expect, test } from 'bun:test'
import { backendRequest } from './backend-request'

const previous = process.env.EDITOR_BACKEND_URL
afterEach(() => {
  if (previous === undefined) delete process.env.EDITOR_BACKEND_URL
  else process.env.EDITOR_BACKEND_URL = previous
})

test('invalid backend configuration returns a controlled unavailable response', async () => {
  for (const value of ['invalid', 'file:///private/config']) {
    process.env.EDITOR_BACKEND_URL = value
    expect((await backendRequest(new Request('http://editor.test/api/v1/design/jobs'), '/api/v1/design/jobs')).status).toBe(503)
  }
})

test('stream forwards event cursor and closes upstream when the subscriber disconnects', async () => {
  let received = ''
  let closed = false
  const server = Bun.serve({ port: 0, fetch(request) {
    received = request.headers.get('last-event-id') || ''
    return new Response(new ReadableStream({
      start(controller) { controller.enqueue(new TextEncoder().encode('data: first\n\n')) },
      cancel() { closed = true },
    }), { headers: { 'Content-Type': 'text/event-stream' } })
  } })
  process.env.EDITOR_BACKEND_URL = server.url.toString()
  const controller = new AbortController()
  try {
    const response = await backendRequest(new Request('http://editor.test/api/v1/design/jobs/id/stream', {
      headers: { 'Last-Event-ID': '17' }, signal: controller.signal,
    }), '/api/v1/design/jobs/id/stream', { stream: true })
    const reader = response.body!.getReader()
    expect(new TextDecoder().decode((await reader.read()).value)).toContain('first')
    expect(received).toBe('17')
    controller.abort()
    await reader.cancel().catch(() => {})
    for (let attempt = 0; attempt < 50 && !closed; attempt++) await Bun.sleep(10)
    expect(closed).toBe(true)
  } finally {
    server.stop(true)
  }
})
