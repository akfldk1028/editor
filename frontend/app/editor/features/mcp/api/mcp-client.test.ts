import { afterEach, expect, test } from 'bun:test'
import { McpClient } from './mcp-client'
import { persistentParams } from '../mcpStore'

const originalFetch = globalThis.fetch
afterEach(() => { globalThis.fetch = originalFetch })
const response = (value: unknown) => new Response(JSON.stringify(value), { headers: { 'Content-Type': 'application/json' } })

test('native MCP operations retain exact input and disconnect sessions', async () => {
  const requests: Array<{ url: string; method?: string; body: unknown }> = []
  globalThis.fetch = (async (url, init) => {
    const body = init?.body ? JSON.parse(String(init.body)) : null
    requests.push({ url: String(url), method: init?.method, body })
    return response(body?.server_params ? { connection_id: 'connection', capabilities: {} }
      : body?.operation ? { type: 'operation_result', operation: body.operation, data: { ok: true } } : {})
  }) as typeof fetch
  const client = new McpClient({ serverParams: { type: 'StdioServerParams', command: 'python', env: { TEST_SECRET: 'private' } } })
  await client.connect()
  expect(client.isConnected).toBe(true)
  await client.callTool('echo', { text: 'hello' })
  expect(requests[1]?.body).toEqual({ operation: 'call_tool', tool_name: 'echo', arguments: { text: 'hello' } })
  await client.readResource('fixture://one')
  expect(requests[2]?.body).toEqual({ operation: 'read_resource', uri: 'fixture://one' })
  client.disconnect()
  expect(client.isConnected).toBe(false)
  expect(requests[3]?.method).toBe('DELETE')
})

test('late connection creation is disposed without notifying a removed page', async () => {
  let complete!: (value: Response) => void
  const creation = new Promise<Response>(resolve => { complete = resolve })
  let disposed = false
  globalThis.fetch = (async (_url, init) => {
    if (init?.method === 'DELETE') { disposed = true; return response({}) }
    return creation
  }) as typeof fetch
  const messages: unknown[] = []
  const client = new McpClient({ serverParams: {}, onMessage: value => messages.push(value) })
  const pending = client.connect()
  client.disconnect()
  complete(response({ connection_id: 'late', capabilities: {} }))
  await pending
  expect(disposed).toBe(true)
  expect(messages).toEqual([])
  expect(client.isConnected).toBe(false)
})

test('connection close aborts a pending operation and suppresses late listeners', async () => {
  let signal: AbortSignal | null | undefined
  let complete!: (value: Response) => void
  const operation = new Promise<Response>(resolve => { complete = resolve })
  globalThis.fetch = (async (_url, init) => {
    const body = init?.body && JSON.parse(String(init.body))
    if (body?.server_params) return response({ connection_id: 'one' })
    if (init?.method === 'DELETE') return response({})
    signal = init?.signal
    return operation
  }) as typeof fetch
  const client = new McpClient({ serverParams: {} })
  await client.connect()
  const messages: unknown[] = []
  client.addListener(value => messages.push(value))
  const pending = client.listResources()
  client.disconnect()
  expect(signal?.aborted).toBe(true)
  complete(response({ type: 'operation_result', operation: 'list_resources', data: {} }))
  await pending
  expect(messages).toEqual([])
})

test('persistent config excludes credential containers and credential-bearing URLs', () => {
  expect(persistentParams({ type: 'StdioServerParams', command: 'python', args: ['-m', 'server'],
    env: { API_KEY: 'private' }, headers: { Authorization: 'private' } })).toEqual({ type: 'StdioServerParams', command: 'python', args: ['-m', 'server'] })
  expect(persistentParams({ url: 'https://example.com/mcp?token=private' })).toEqual({})
  expect(persistentParams({ url: 'https://user:pass@example.com/mcp' })).toEqual({})
  expect(persistentParams({ url: 'http://127.0.0.1:8000/mcp' })).toEqual({ url: 'http://127.0.0.1:8000/mcp' })
})
