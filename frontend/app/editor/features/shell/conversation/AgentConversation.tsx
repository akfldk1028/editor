'use client'

import { Send, SquarePen, Workflow } from 'lucide-react'
import { useEffect, useRef } from 'react'

import { clearFeed, dismissFeed, type FeedAction, type FeedCard, type FeedEntry, useFeed } from '@/lib/orchestrator-runs/feed'
import { agentLabel } from '@/lib/orchestrator-runs/labels'
import { leadOf, threadOf, type Turn } from '@/lib/orchestrator-runs/thread'

import type { ShellApi } from '../artifact-types'
import './agent-conversation.css'

const time = (at: number) => new Date(at).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false })

/** The conversation's identity block for the shell's header row. */
export function AgentConversationHeading() {
  return (
    <div className="agent-heading">
      <span aria-hidden="true" className="agent-heading-mark"><Workflow size={14} /></span>
      <div>
        <strong>에이전트 대화</strong>
        <span>오케스트레이터 · 대지 · 법규 · 검토 조정</span>
      </div>
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
            <strong>대지를 선택하면 여기서 답해요</strong>
            <span>지도에서 필지를 고르고 <b>이 대지로 선택</b> → <b>검토 시작</b>을 누르면 대지·법규·검토 조정 에이전트가 차례로 이 대화에 답해요.</span>
          </div>
        ) : (
          turns.map((turn) => <TurnView key={turnKey(turn)} shell={shell} turn={turn} />)
        )}
        <div ref={endRef} />
      </div>
      <form className="agent-composer" onSubmit={(event) => event.preventDefault()}>
        <input aria-label="에이전트에게 보낼 말" disabled placeholder="에이전트에게 말하기 — 다음 단계에서 연결돼요" type="text" />
        <button aria-label="보내기" className="agent-composer-send" disabled type="submit"><Send size={15} /></button>
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

/** Speaker row: the agent's initial as its mark, its Korean name, the time. */
function Who({ agent, at }: { agent: string; at: number }) {
  const label = agentLabel(agent)
  return (
    <header className="agent-turn-who">
      <span aria-hidden="true" className="agent-turn-mark">{agent === 'orchestrator' ? 'O' : label.slice(0, 1)}</span>
      <b>{label}</b>
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
      {entry.card && <Card card={entry.card} />}
      {entry.actions?.map((action) => (
        <button className="agent-turn-link" key={action.label} onClick={() => act(action, shell)} type="button">{action.label}</button>
      ))}
    </Tag>
  )
}

function Card({ card }: { card: FeedCard }) {
  if (card.type === 'stats') {
    return (
      <dl className="agent-stats">
        {card.items.map((item) => (
          <div key={item.label}><dt>{item.label}</dt><dd>{item.value}</dd></div>
        ))}
      </dl>
    )
  }
  return <ul className="agent-chips">{card.items.map((item) => <li key={item}>{item}</li>)}</ul>
}

function act(action: FeedAction, shell: ShellApi) {
  if (action.artifact) shell.openArtifact(action.artifact, action.params)
}
