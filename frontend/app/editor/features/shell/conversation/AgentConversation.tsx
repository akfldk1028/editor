'use client'

import { Send, SquarePen, Workflow } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { dismissFeed, type FeedEntry, useFeed, feedForProject, projectFeed } from '@/lib/orchestrator-runs/feed'
import { askLines, siteLocateParams, siteLocatedLine } from '@/lib/orchestrator-runs/feed-lines'
import { newConversation, useConversationSelection } from '@/lib/design-conversation/session'
import { turnSteps, useLedger, waitingLine } from '@/lib/ledger'
import { useConversation } from '@/lib/design-conversation/useConversation'
import { conversationErrorText } from '@/lib/design-conversation/errors'
import { designConversationContext } from '@/lib/design-conversation/context'
import { loadRunConditions } from '@/lib/orchestrator-runs/conditions'
import { onCommand } from '@/lib/orchestrator-runs/commands'
import { agentLabel } from '@/lib/orchestrator-runs/labels'
import { conversationTitle, leadOf, threadOf, type Turn } from '@/lib/orchestrator-runs/thread'
import { useAsk } from '@/lib/orchestrator-runs/useAsk'

import type { ShellApi } from '../artifact-types'
import { act } from './act'
import { AgentMark } from './agentMarks'
import { FeedCard } from './FeedCard'
import { AskedAgents, StepList } from './AgentSteps'
import { ConversationArtifacts } from './ConversationArtifacts'
import { ConversationProject, useConversationProject } from './ConversationProject'
import './agent-conversation.css'

/** When the question a reply answers was asked: the nearest earlier message from the person, or null. */
function askedAt(messages: readonly { role: string; at: string }[], index: number): number | null {
  for (let at = index - 1; at >= 0; at--) if (messages[at]!.role === 'user') return Date.parse(messages[at]!.at)
  return null
}

const time = (at: number) => new Date(at).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false })

/**
 * The header row: nothing while the conversation is empty (like a fresh ChatGPT chat); once it has
 * content, the site it is about and where the review stands, compressed to one block.
 */
export function AgentConversationHeading() {
  const selection = useConversationSelection()
  const entries = feedForProject(useFeed(), selection.projectId, selection.conversationId)
  const title = conversationTitle(entries)
  if (!title) return <div className="agent-heading" />
  return (
    <div className="agent-heading">
      <strong>{title.title}</strong>
      {title.subtitle && <span>{title.subtitle}</span>}
    </div>
  )
}

export function AgentConversationActions() {
  // Until the page is interactive a press would be lost, so the button says so instead of looking ready.
  const [ready, setReady] = useState(false)
  useEffect(() => { setReady(true) }, [])
  return (
    <button aria-label="새 대화" className="icon-button" disabled={!ready} onClick={newConversation} title="새 대화 · 이전 대화는 저장됩니다" type="button">
      <SquarePen size={17} />
    </button>
  )
}

/**
 * The centre column as a conversation with the agent network, in the shape of a chat. The user's
 * lines (대지 선택, 검토 시작) are their bubbles on the right; receipts are small centred lines; each
 * agent speaks in its own turn (avatar + name — 대지, 법규, 검토 조정), its steps folded under the lead
 * line, Law's numbers as tiles, missing evidence as chips; the Orchestrator moderates and asks the
 * closing question ("법규를 보시겠어요?") whose buttons are the answers. Entries come from
 * `lib/orchestrator-runs/feed`; artifact slices post them.
 */
export function AgentConversation({ shell }: { shell: ShellApi }) {
  const selection = useConversationSelection()
  const entries = feedForProject(useFeed(), selection.projectId, selection.conversationId)
  const turns = threadOf(entries)
  const endRef = useRef<HTMLDivElement>(null)
  const composerRef = useRef<HTMLInputElement>(null)
  useAsk(shell.openArtifact)
  const project = useConversationProject()
  // The editor located a site the message named: the Site Agent's line goes to the feed and the map opens on that
  // parcel and selects it. A message that was one address never reached the owner, so its bubble is posted here too.
  // The ledger of this conversation, so the waiting line names the agent being asked right now.
  const ledger = useLedger(project.projectId ? { conversation_id: project.conversationId } : null)
  const steps = turnSteps(ledger.messages)
  const conversation = useConversation(project.projectId, project.conversationId, (located, text) => {
    const postFeed = projectFeed(project.projectId, project.conversationId)
    if (text) postFeed(askLines(text)[0]!)
    postFeed(siteLocatedLine(located))
    const params = siteLocateParams(located)
    if (params) shell.openArtifact('site-map', params)
  })
  const messages = conversation.snapshot?.messages ?? []
  const count = entries.length + messages.length + conversation.pending.length
  const timeline = [
    ...turns.map((turn) => ({ at: turn.kind === 'agent' ? turn.at : turn.entry.at, key: `feed-${turnKey(turn)}`, node: <TurnView shell={shell} turn={turn} /> })),
    ...messages.map((message, index) => ({ at: Date.parse(message.at), key: `saved-${message.id}`, node: message.role === 'user' ? (
      <div className="agent-turn-user"><p>{message.text}</p><time dateTime={message.at}>{time(Date.parse(message.at))}</time></div>
    ) : (
      <article className="agent-turn conversation-message"><Who agent={message.agent ?? 'orchestrator'} at={Date.parse(message.at)} />
        {/* A question's last reply (after any notes sent while it worked) carries what the agents were asked for it, folded. */}
        {messages[index + 1]?.role !== 'assistant' && askedAt(messages, index) !== null &&
          <AskedAgents steps={turnSteps(ledger.messages, {}, { since: askedAt(messages, index)!, until: Date.parse(message.at) })} />}
        <p>{message.text}</p></article>
    ) })),
    ...conversation.pending.map((pending) => ({ at: Date.parse(pending.at), key: `pending-${pending.body.message_id}`, node: <div className="agent-turn-user">
      <p>{pending.body.text}</p>
      {pending.error ? <div role="alert">{pending.error}<button className="agent-turn-link" type="button" onClick={() => conversation.retry?.(pending.body.message_id)}>다시 전송</button><button className="agent-turn-link" type="button" onClick={() => conversation.discard?.(pending.body.message_id)}>실패한 메시지 삭제</button></div> : <span role="status">{pending.delivery === 'waiting' ? '전송 대기 · 앞선 작업이 끝나면 이어서 보낼게요' : pending.delivery === 'sent' ? '접수를 확인하는 중…' : '보내는 중…'}</span>}
    </div> })),
  ].sort((a, b) => a.at - b.at)
  const draftKey = JSON.stringify([project.projectId, project.conversationId])
  const [draftValue, setDraftValue] = useState({ key: '', text: '' })
  const draft = draftValue.key === draftKey ? draftValue.text : ''
  const setDraft = (text: string) => setDraftValue({ key: draftKey, text })
  useEffect(() => onCommand((command) => {
    if (command.kind !== 'compose') return
    setDraftValue((current) => current.key === draftKey && current.text.trim() ? current : { key: draftKey, text: command.draft })
    if (composerRef.current?.disabled) document.querySelector<HTMLSelectElement>('.conversation-project select')?.focus()
    else composerRef.current?.focus()
  }), [draftKey])
  const submit = () => {
    const text = draft.trim()
    if (!text || !project.projectId || !conversation.send || conversation.loading) return
    conversation.send(text, { assessment_date: loadRunConditions().assessmentDate, ...designConversationContext(project.projectId) })
    setDraft('')
  }

  // The newest turn stays in view; only the thread scrolls.
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'end' })
  }, [count])

  return (
    <section aria-label="에이전트 대화" className="agent-conversation">
      <div aria-live="polite" className="agent-thread">
        <ConversationProject {...project} />
        {turns.length === 0 && messages.length === 0 && !conversation.pending.length ? (
          <div className="agent-thread-empty">
            <Workflow aria-hidden="true" size={28} />
            <strong>무엇을 도와드릴까요?</strong>
            <span>프로젝트를 고르고 원하는 공간이나 바꾸고 싶은 점을 이야기해 주세요.</span>
          </div>
        ) : (
          timeline.map((item) => <div key={item.key}>{item.node}</div>)
        )}
        {conversation.loading && <p className="agent-turn-system" role="status">저장된 대화를 불러오는 중…</p>}
        {conversation.snapshot?.status === 'working' && (
          <div className="agent-turn-steps" role="status">
            <p className="agent-turn-system"><span aria-hidden="true" className="loading-mark" />{waitingLine(ledger.messages)}</p>
            {/* What each agent was asked in this turn, as a chat app shows its tool steps: who, what, how many, done or not. */}
            <StepList steps={steps} />
          </div>
        )}
        {(conversation.error || conversation.snapshot?.error) && <div className="agent-turn-system" role="alert">{conversation.error || conversationErrorText(conversation.snapshot?.error)}<button className="agent-turn-link" onClick={() => void conversation.refresh?.()} title="저장된 대화 상태를 다시 불러옵니다" type="button">상태 새로고침</button></div>}
        <ConversationArtifacts artifacts={conversation.snapshot?.artifacts ?? []} onConfirm={conversation.confirm} disabled={conversation.loading || conversation.snapshot?.status === 'working' || conversation.pending.length > 0} />
        <div ref={endRef} />
      </div>
      <form
        className="agent-composer"
        onSubmit={(event) => {
          event.preventDefault()
          submit()
        }}
      >
        <input
          ref={composerRef}
          aria-label="메시지"
          autoComplete="off"
          maxLength={8000}
          disabled={!project.projectId || conversation.loading}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="원하는 공간, 조건, 바꾸고 싶은 점을 이야기해 주세요"
          type="text"
          value={draft}
        />
        <button aria-label="보내기" className="agent-composer-send" disabled={!project.projectId || conversation.loading || !draft.trim()} type="submit">
          <Send size={15} />
        </button>
      </form>
    </section>
  )
}

const turnKey = (turn: Turn) => (turn.kind === 'agent' ? `a${turn.id}` : `e${turn.entry.id}`)

function TurnView({ turn, shell }: { turn: Turn; shell: ShellApi }) {
  if (turn.kind === 'user') {
    return (
      <div className="agent-turn-user">
        <p>{turn.entry.text}</p>
        <time dateTime={new Date(turn.entry.at).toISOString()}>{time(turn.entry.at)}</time>
      </div>
    )
  }
  if (turn.kind === 'system') {
    const { entry } = turn
    return (
      <div className="agent-turn-system">
        <time dateTime={new Date(entry.at).toISOString()}>{time(entry.at)}</time>
        <span>{entry.text}</span>
      </div>
    )
  }
  if (turn.kind === 'prompt') {
    const { entry } = turn
    return (
      <article className="agent-turn" data-agent={entry.agent ?? 'orchestrator'} data-kind="prompt">
        <Who agent={entry.agent ?? 'orchestrator'} at={entry.at} />
        <p>{entry.text}</p>
        <div className="agent-answers">
          {entry.actions?.map((action, index) => (
            <button
              className="agent-answer"
              data-primary={index === 0 ? 'true' : undefined}
              key={action.label}
              onClick={() => {
                act(action, shell)
                dismissFeed(entry.id)
              }}
              type="button"
            >
              {action.label}
            </button>
          ))}
        </div>
      </article>
    )
  }
  const lead = leadOf(turn)
  if (lead.relay && turn.steps.length === 1) return <RelayView entry={lead} />
  const steps = turn.steps.filter((step) => step !== lead)
  return (
    <article className="agent-turn" data-agent={turn.agent} data-error={turn.error ? 'true' : undefined}>
      <Who agent={turn.agent} at={turn.at} />
      {steps.length > 0 && (
        <ol className="agent-steps">
          {steps.map((step) => <Step entry={step} key={step.id} shell={shell} />)}
        </ol>
      )}
      <Step entry={lead} lead shell={shell} />
    </article>
  )
}

/**
 * A request in flight, drawn: who asks ⟶ who is asked, the connector pulsing while the line lives
 * (it is dismissed when the answer arrives), the request named under it.
 */
function RelayView({ entry }: { entry: FeedEntry }) {
  const { from, to } = entry.relay!
  return (
    <div aria-live="polite" className="agent-relay" role="status">
      <div className="agent-relay-party">
        <AgentMark agent={from} size={18} />
        <span>{agentLabel(from)}</span>
      </div>
      <div aria-hidden="true" className="agent-relay-track"><i /><i /><i /></div>
      <div className="agent-relay-party" data-target="true">
        <AgentMark agent={to} size={18} />
        <span>{agentLabel(to)}</span>
      </div>
      <p>{entry.text}</p>
    </div>
  )
}

/** Speaker row: the agent's own mark, its network name, the time. */
function Who({ agent, at }: { agent: string; at: number }) {
  return (
    <header className="agent-turn-who">
      <AgentMark agent={agent} />
      <b>{agentLabel(agent)}</b>
      <time dateTime={new Date(at).toISOString()}>{time(at)}</time>
    </header>
  )
}

function Step({ entry, lead = false, shell }: { entry: FeedEntry; lead?: boolean; shell: ShellApi }) {
  const Tag = lead ? 'div' : 'li'
  return (
    <Tag className={lead ? 'agent-lead' : undefined} data-kind={entry.kind} data-tone={entry.tone}>
      <p>
        {entry.tone && <span aria-hidden="true" className="agent-dot" />}
        {entry.text}
      </p>
      {entry.card && <FeedCard card={entry.card} />}
      {entry.actions?.map((action) => (
        <button className="agent-turn-link" key={action.label} onClick={() => act(action, shell)} type="button">{action.label}</button>
      ))}
    </Tag>
  )
}
