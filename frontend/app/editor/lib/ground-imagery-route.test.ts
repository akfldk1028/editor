import { afterEach, expect, test } from 'bun:test'
import { GET } from '../app/api/v1/land/ground-imagery/[...tile]/route'

const originalFetch = globalThis.fetch
const originalBackend = process.env.EDITOR_BACKEND_URL
afterEach(() => {
  globalThis.fetch = originalFetch
  if (originalBackend === undefined) delete process.env.EDITOR_BACKEND_URL
  else process.env.EDITOR_BACKEND_URL = originalBackend
})

test('fine ground PNG reaches the backend and keeps its binary response and cache policy', async () => {
  process.env.EDITOR_BACKEND_URL = 'http://backend.test'
  let destination = ''
  const bytes = new Uint8Array([137, 80, 78, 71, 1, 2, 3])
  globalThis.fetch = Object.assign(async (url: RequestInfo | URL) => {
    destination = String(url)
    return new Response(bytes, { headers: { 'Content-Type': 'image/png', 'Cache-Control': 'public, max-age=86400' } })
  }, { preconnect: originalFetch.preconnect }) as typeof fetch
  const response = await GET(new Request('http://editor.test/api/v1/land/ground-imagery/15/27953/12666.png'),
    { params: Promise.resolve({ tile: ['15', '27953', '12666.png'] }) })
  expect(destination).toBe('http://backend.test/api/v1/land/ground-imagery/15/27953/12666.png')
  expect(response.status).toBe(200)
  expect(response.headers.get('Content-Type')).toBe('image/png')
  expect(response.headers.get('Cache-Control')).toBe('public, max-age=86400')
  expect(new Uint8Array(await response.arrayBuffer())).toEqual(bytes)
})

test('low zooms, out-of-range coordinates and arbitrary paths never reach the backend', async () => {
  let calls = 0
  globalThis.fetch = Object.assign(async () => { calls++; return new Response() }, { preconnect: originalFetch.preconnect }) as typeof fetch
  for (const tile of [['12', '1', '1.png'], ['18', '1', '1.png'], ['13', '8192', '0.png'],
    ['17', '0', '131072.png'], ['13', '-1', '0.png'], ['13', '1', '../source.png']]) {
    expect((await GET(new Request('http://editor.test/'), { params: Promise.resolve({ tile }) })).status).toBe(400)
  }
  expect(calls).toBe(0)
})
