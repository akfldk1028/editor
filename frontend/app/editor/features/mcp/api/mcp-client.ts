export interface McpWsMessage {
  type: 'initialized' | 'operation_result' | 'operation_error'
  operation?: string
  data?: unknown
  error?: string
}
interface Options {
  serverParams: Record<string, unknown>
  onMessage?: (message: McpWsMessage) => void
  onClose?: () => void
  onError?: (error: Error) => void
}

const base = `${process.env.NEXT_PUBLIC_BASE_PATH || ''}/api/v1/workspace/mcp/connections`

export class McpClient {
  private id: string | null = null
  private closed = false
  private controllers = new Set<AbortController>()
  private listeners = new Set<(message: McpWsMessage) => void>()
  constructor(private options: Options) {}
  get isConnected() { return this.id !== null && !this.closed }
  addListener(listener: (message: McpWsMessage) => void) {
    this.listeners.add(listener)
    return () => { this.listeners.delete(listener) }
  }
  private emit(message: McpWsMessage) {
    if (this.closed) return
    this.options.onMessage?.(message)
    for (const listener of this.listeners) listener(message)
  }
  private async request(url: string, body: unknown, abortOnClose = true) {
    const controller = new AbortController()
    if (abortOnClose) this.controllers.add(controller)
    const timeout = setTimeout(() => controller.abort(), 60_000)
    try {
      const response = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body), signal: controller.signal })
      if (!response.ok) throw new Error(`MCP request failed (${response.status})`)
      return await response.json()
    } finally {
      clearTimeout(timeout)
      this.controllers.delete(controller)
    }
  }
  async connect() {
    if (this.closed || this.id) throw new Error('MCP client is already connected or closed')
    try {
      // Keep the creation response long enough to dispose an in-flight session on unmount.
      const value = await this.request(base, { server_params: this.options.serverParams }, false)
      if (typeof value.connection_id !== 'string' || !value.connection_id) throw new Error('Invalid MCP connection response')
      if (this.closed) {
        await this.release(value.connection_id)
        return
      }
      this.id = value.connection_id
      this.emit({ type: 'initialized', data: value.capabilities })
    } catch (error) {
      if (!this.closed) this.options.onError?.(error instanceof Error ? error : new Error('MCP connection failed'))
      throw error
    }
  }
  private async release(id: string) {
    await fetch(`${base}/${encodeURIComponent(id)}`, { method: 'DELETE', keepalive: true }).catch(() => {})
  }
  disconnect() {
    if (this.closed) return
    this.closed = true
    for (const controller of this.controllers) controller.abort()
    this.controllers.clear()
    this.listeners.clear()
    const id = this.id
    this.id = null
    if (id) void this.release(id)
    this.options.onClose?.()
  }
  private async operation(operation: string, values: Record<string, unknown> = {}) {
    try {
      if (!this.isConnected) throw new Error('MCP server is not connected')
      const message: McpWsMessage = await this.request(`${base}/${encodeURIComponent(this.id!)}/operations`, { operation, ...values })
      if (this.closed) throw new Error('MCP connection closed')
      if (message.operation !== operation || !['operation_result', 'operation_error'].includes(message.type)) {
        throw new Error('Invalid MCP operation response')
      }
      this.emit(message)
      return message
    } catch (error) {
      const message: McpWsMessage = { type: 'operation_error', operation,
        error: error instanceof Error ? error.message : 'MCP operation failed' }
      this.emit(message)
      return message
    }
  }
  listTools() { return this.operation('list_tools') }
  callTool(toolName: string, args: Record<string, unknown>) { return this.operation('call_tool', { tool_name: toolName, arguments: args }) }
  listResources() { return this.operation('list_resources') }
  readResource(uri: string) { return this.operation('read_resource', { uri }) }
}
