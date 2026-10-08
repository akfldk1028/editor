'use client'

import { Send, SquarePen, Workflow } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { clearFeed, dismissFeed, type FeedEntry, useFeed } from '@/lib/orchestrator-runs/feed'
import { agentLabel } from '@/lib/orchestrator-runs/labels'
import { conversationTitle, leadOf, threadOf, type Turn } from '@/lib/orchestrator-runs/thread'
import { useAsk } from '@/lib/orchestrator-runs/useAsk'

import type { ShellApi } from '../artifact-types'
import { act } from './act'
import { AgentMark } from './agentMarks'
import { FeedCard } from './FeedCard'
import './agent-conversation.css'

const time = (at: number) => new Date(at).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false })

/**
 * The header row: nothing while the conversation is empty (like a fresh ChatGPT chat); once it has
 * content, the site it is about and where the review stands, compressed to one block.
 */
export function AgentConversationHeading() {
  const entries = useFeed()
  const title = conversationTitle(entries)
  if (!title) return <div className="agent-heading" />
  return (
    <div className="agent-heading">
      <strong>{title.title}</strong>
      {title.subtitle && <span>{title.subtitle}</span>}
    </div>
  )
}

/** Header controls: start the conversation over (the feed is this session's memory). */
export function AgentConversationActions() {
  return (
    <button aria-label="새 대화" className="icon-button" onClick={clearFeed} title="새 대화" type="button">
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
  const entries = useFeed()
  const turns = threadOf(entries)
  const endRef = useRef<HTMLDivElement>(null)
  const count = entries.length
  const { send, busy } = useAsk()
  const [draft, setDraft] = useState('')
  const submit = () => {
    const text = draft.trim()
    if (!text || busy) return
    setDraft('')
    void send(text)
  }

  // The newest turn stays in view; only the thread scrolls.
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'end' })
  }, [count])

  return (
    <section aria-label="에이전트 대화" className="agent-conversation">
      <div aria-live="polite" className="agent-thread">
        {turns.length === 0 ? (
          <div className="agent-thread-empty">
            <Workflow aria-hidden="true" size={28} />
            <strong>무엇을 도와드릴까요?</strong>
            <span>지도에서 대지를 고르면 시작돼요.</span>
          </div>
        ) : (
          turns.map((turn) => <TurnView key={turnKey(turn)} shell={shell} turn={turn} />)
        )}
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
          aria-label="메시지"
          autoComplete="off"
          maxLength={500}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="무엇이든 물어보세요 — 예: 뭐 할 수 있어?, 자연녹지지역 건폐율, 매스 쌓아 봐"
          type="text"
          value={draft}
        />
        <button aria-label="보내기" className="agent-composer-send" disabled={busy || !draft.trim()} type="submit">
          {busy ? <span aria-hidden="true" className="loading-mark" /> : <Send size={15} />}
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
