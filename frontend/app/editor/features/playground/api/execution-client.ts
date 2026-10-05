export interface FileAttachment { name: string; type: string; content: string }
export interface WSMessage {
  type: string
  data?: unknown
  status?: string
  error?: string
  timestamp?: string
  source?: string
  content?: string
  seq?: number
}
interface Options {
  runId: number | string
  sessionId?: number
  onMessage: (message: WSMessage) => void
  onClose?: () => void
  onError?: (error: string) => void
}

// The native BFF uses a durable event cursor: refresh/retry never repeats a run.
export class ExecutionClient {
  private active = false
  private polling = false
  private cursor = 0
  private timer: ReturnType<typeof setTimeout> | undefined
  private controller = new AbortController()
  private root: string
  constructor(private options: Options) {
    this.root = `${process.env.NEXT_PUBLIC_BASE_PATH || ''}/api/v1/workspace/runs/${encodeURIComponent(options.runId)}`
  }
  private async request(path: string, body?: unknown) {
    const response = await fetch(this.root + path, {
      method: body === undefined ? 'GET' : 'POST', signal: this.controller.signal,
      headers: {'Content-Type':'application/json'},
      body: body === undefined ? undefined : JSON.stringify(body), cache:'no-store',
    })
    if (!response.ok) throw new Error(`Execution request failed (${response.status})`)
    return response.json()
  }
  async connect() {
    const result = await this.request('/events')
    if (String(result.run_id) !== String(this.options.runId)) throw new Error('Execution identity mismatch')
    if (this.options.sessionId !== undefined && result.session_id !== this.options.sessionId) throw new Error('Execution session mismatch')
    if (this.controller.signal.aborted) return
    this.active = true
  }
  async resume() { await this.connect(); if (this.active) void this.poll() }
  async startExecution(task: string, _teamConfig?: unknown, files?: FileAttachment[]) {
    try {
      await this.request('/start', {task,files:files || []})
      if (this.active) void this.poll()
    } catch (error) { this.fail(error); throw error }
  }
  private async poll() {
    if (this.polling || !this.active) return
    this.polling = true
    clearTimeout(this.timer)
    try {
      const result = await this.request(`/events?after=${this.cursor}`)
      if (!this.active) return
      if (String(result.run_id) !== String(this.options.runId) || !Array.isArray(result.events)) throw new Error('Execution response mismatch')
      for (const event of result.events as WSMessage[]) {
        if (!event.seq || event.seq <= this.cursor) continue
        this.options.onMessage(event)
        this.cursor = event.seq
      }
      if (['complete','error','stopped','timeout'].includes(result.status) && !result.has_more) {
        this.active = false
        this.options.onClose?.()
      } else {
        this.timer = setTimeout(() => void this.poll(), result.has_more ? 0 : 250)
      }
    } catch (error) { this.fail(error) }
    finally { this.polling = false }
  }
  private fail(error: unknown) {
    if (this.controller.signal.aborted) return
    this.active = false
    this.options.onError?.(error instanceof Error ? error.message : 'Execution transport failed')
  }
  async sendInput(response: string) {
    try { await this.request('/input', {response}) }
    catch (error) { this.fail(error); throw error }
  }
  async stop() {
    try { await this.request('/stop', {}); this.active = true; await this.poll() }
    catch (error) { this.fail(error) }
  }
  get isConnected() { return this.active }
  disconnect() {
    this.active = false
    clearTimeout(this.timer)
    this.controller.abort()
  }
}
