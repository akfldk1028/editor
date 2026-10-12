import { getConversation, postConversation } from './client'
import { confirmationFor } from './confirmation'
import { designConversationContext } from './context'
import type { SiteLocateBody } from '@/lib/orchestrator-runs/types'
import type { ConversationArtifact, ConversationContext, ConversationSnapshot, ConversationSubmission } from './types'

export interface PendingMessage { body: ConversationSubmission; at: string; error: string | null; delivery: 'waiting' | 'sending' | 'sent' | 'failed' }
export interface ConversationState { snapshot: ConversationSnapshot | null; loading: boolean; error: string | null; pending: PendingMessage[] }
interface Transport { get: typeof getConversation; post: typeof postConversation }

export class ConversationController {
  private state: ConversationState = { snapshot: null, loading: true, error: null, pending: [] }
  private listeners = new Set<() => void>()
  private timer: ReturnType<typeof setTimeout> | undefined
  private active = false
  private readController: AbortController | null = null
  private posting = false
  /** The editor located a site the message named; the conversation opens the map. `text` is the message when it was
   *  one address (the owner never saw it, the conversation shows the bubble itself), null when the owner has it. */
  onLocated: ((located: SiteLocateBody, text: string | null) => void) | null = null
  constructor(readonly projectId: string, readonly conversationId: string, private transport: Transport = { get: getConversation, post: postConversation }, private interval = 1200, private idleInterval = 15000) {}
  getSnapshot = () => this.state
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener) } }
  private update(patch: Partial<ConversationState>) {
    this.state = { ...this.state, ...patch }
    this.listeners.forEach((listener) => { listener() })
  }
  start = () => { this.active = true; void this.refresh() }
  stop = () => { this.active = false; clearTimeout(this.timer); this.readController?.abort() }
  private schedule() {
    clearTimeout(this.timer)
    if (this.active) {
      const busy = this.state.snapshot?.status === 'working' || this.state.error || this.state.pending.length
      this.timer = setTimeout(() => void this.refresh(), busy ? this.interval : this.idleInterval)
    }
  }
  private accept(snapshot: ConversationSnapshot) {
    if (snapshot.conversation_id !== this.conversationId) throw new Error('다른 대화의 응답을 받았어요. 다시 연결해 주세요.')
    if (snapshot.revision < (this.state.snapshot?.revision ?? -1)) return
    const confirmed = new Set(snapshot.messages.map((message) => message.id))
    this.update({ snapshot, loading: false, error: null, pending: this.state.pending.filter((pending) => !confirmed.has(pending.body.message_id)) })
  }
  refresh = async () => {
    if (!this.active) return
    this.readController?.abort()
    const controller = new AbortController()
    this.readController = controller
    try {
      const snapshot = await this.transport.get(this.projectId, this.conversationId, controller.signal)
      if (this.active && !controller.signal.aborted) this.accept(snapshot)
    } catch (error) {
      if (this.active && !controller.signal.aborted) this.update({ loading: false, error: error instanceof Error ? error.message : '대화를 불러오지 못했어요.' })
    } finally {
      if (this.readController === controller) this.readController = null
      if (!controller.signal.aborted) { this.drain(); this.schedule() }
    }
  }
  send = (text: string, context: ConversationContext) => {
    this.submit(text, context)
  }
  confirm = (artifact: ConversationArtifact) => {
    if (this.state.snapshot?.status === 'working' || this.state.pending.length) return
    const current = this.state.snapshot?.artifacts.find((item) => item.id === artifact.id)
    const confirmation = current && confirmationFor(current)
    if (!confirmation || confirmation.context_hash !== confirmationFor(artifact)?.context_hash) return
    this.submit('변경된 조건을 기준으로 이 설계 의도를 확인합니다.', designConversationContext(this.projectId), confirmation)
  }
  private submit(text: string, context: ConversationContext, confirmation?: ConversationSubmission['confirmation']) {
    if (!text.trim() || text.length > 8000 || this.state.loading || !this.active) return
    const pending: PendingMessage = { body: { conversation_id: this.conversationId, message_id: crypto.randomUUID(), text: text.trim(), context, ...(confirmation ? { confirmation } : {}) }, at: new Date().toISOString(), error: null, delivery: 'waiting' }
    this.update({ pending: [...this.state.pending, pending] })
    this.drain()
    this.schedule()
  }
  retry = (messageId: string) => {
    const pending = this.state.pending.find((item) => item.body.message_id === messageId)
    if (pending?.error) {
      this.update({ pending: this.state.pending.map((item) => item === pending ? { ...item, error: null, delivery: 'waiting' } : item) })
      this.drain()
      this.schedule()
    }
  }
  discard = (messageId: string) => {
    const pending = this.state.pending.find((item) => item.body.message_id === messageId)
    if (pending?.delivery !== 'failed') return
    this.update({ pending: this.state.pending.filter((item) => item !== pending) })
    this.drain()
    this.schedule()
  }
  private drain() {
    if (!this.active || this.posting || this.readController || this.state.loading || this.state.error || this.state.snapshot?.status === 'working') return
    const next = this.state.pending[0]
    if (next?.delivery === 'waiting') void this.dispatch(next)
  }
  private async dispatch(pending: PendingMessage) {
    this.posting = true
    this.update({ pending: this.state.pending.map((item) => item === pending ? { ...item, error: null, delivery: 'sending' } : item) })
    try {
      const result = await this.transport.post(this.projectId, pending.body)
      if (!('conversation_id' in result)) {
        this.update({ pending: this.state.pending.filter((item) => item.body.message_id !== pending.body.message_id) })
        this.onLocated?.(result.located, pending.body.text)
        return
      }
      this.update({ pending: this.state.pending.map((item) => item.body.message_id === pending.body.message_id ? { ...item, delivery: 'sent' } : item) })
      const { located, ...snapshot } = result
      this.accept(snapshot)
      if (located) this.onLocated?.(located, null)
    } catch (error) {
      this.update({ pending: this.state.pending.map((item) => item.body.message_id === pending.body.message_id ? { ...item, delivery: 'failed', error: error instanceof Error ? error.message : '전송 여부를 확인하지 못했어요.' } : item) })
    } finally { this.posting = false; this.drain(); this.schedule() }
  }
}
