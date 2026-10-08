'use client'

import { X } from 'lucide-react'
import { useEffect, useRef } from 'react'

import { clearFeed, dismissFeed, type FeedAction, type FeedCard, type FeedEntry, useFeed } from '@/lib/orchestrator-runs/feed'

import type { ShellApi } from '../artifact-types'
import './agent-feed.css'

const time = (at: number) => new Date(at).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false })

/**
 * The agent stream above the conversation: what the Orchestrator network relayed about the selected
 * site, posted by artifact slices through `lib/orchestrator-runs/feed`. Lines stay system-styled (no
 * bubble, small time); a step carries a tone dot, Law's numbers come as stat tiles, missing evidence as
 * chips, and a `prompt` is the network's question in a bubble whose buttons answer it (an action with
 * an artifact opens it through the shell; any answer dismisses the prompt). Renders nothing while empty.
 */
export function AgentFeed({ shell }: { shell: ShellApi }) {
  const entries = useFeed()
  const listRef = useRef<HTMLOListElement>(null)
  const count = entries.length

  // The newest line stays in view; the list only scrolls itself, never the page.
  useEffect(() => {
    const list = listRef.current
    if (list) list.scrollTop = list.scrollHeight
  }, [count])

  if (count === 0) return null
  return (
    <section aria-label="에이전트 진행" aria-live="polite" className="agent-feed">
      <header>
        <span>에이전트</span>
        <button aria-label="에이전트 진행 지우기" className="icon-button agent-feed-clear" onClick={clearFeed} title="지우기" type="button">
          <X size={14} />
        </button>
      </header>
      <ol ref={listRef}>
        {entries.map((entry) => (entry.kind === 'prompt' ? <Prompt entry={entry} key={entry.id} shell={shell} /> : <Line entry={entry} key={entry.id} shell={shell} />))}
      </ol>
    </section>
  )
}

function Line({ entry, shell }: { entry: FeedEntry; shell: ShellApi }) {
  return (
    <li data-kind={entry.kind} data-tone={entry.tone}>
      <time dateTime={new Date(entry.at).toISOString()}>{time(entry.at)}</time>
      <p>
        {entry.tone && <span aria-hidden="true" className="agent-feed-dot" />}
        {entry.text}
      </p>
      {entry.card && <Card card={entry.card} />}
      {entry.actions?.map((action) => (
        <button className="agent-feed-action" key={action.label} onClick={() => act(action, shell)} type="button">
          {action.label}
        </button>
      ))}
    </li>
  )
}

/** The network's question, phrased like a reply in the conversation; its buttons are the answers. */
function Prompt({ entry, shell }: { entry: FeedEntry; shell: ShellApi }) {
  return (
    <li data-kind="prompt">
      <time dateTime={new Date(entry.at).toISOString()}>{time(entry.at)}</time>
      <div className="agent-feed-prompt" role="group" aria-label="에이전트 질문">
        <p>{entry.text}</p>
        <div className="agent-feed-answers">
          {entry.actions?.map((action, index) => (
            <button
              className="agent-feed-answer"
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
      </div>
    </li>
  )
}

function Card({ card }: { card: FeedCard }) {
  if (card.type === 'stats') {
    return (
      <dl className="agent-feed-stats">
        {card.items.map((item) => (
          <div key={item.label}>
            <dt>{item.label}</dt>
            <dd>{item.value}</dd>
          </div>
        ))}
      </dl>
    )
  }
  return (
    <ul className="agent-feed-chips">
      {card.items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  )
}

function act(action: FeedAction, shell: ShellApi) {
  if (action.artifact) shell.openArtifact(action.artifact, action.params)
}
