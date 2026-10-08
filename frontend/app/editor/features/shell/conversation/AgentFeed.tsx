'use client'

import { X } from 'lucide-react'
import { useEffect, useRef } from 'react'

import { clearFeed, type FeedEntry, useFeed } from '@/lib/orchestrator-runs/feed'

import type { ShellApi } from '../artifact-types'
import './agent-feed.css'

const time = (at: number) => new Date(at).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false })

/**
 * The agent stream above the conversation: system-styled lines (no bubble, small time) about the
 * selected site and its Orchestrator runs, posted by artifact slices through `lib/orchestrator-runs/feed`.
 * Action buttons open artifacts through the shell. Renders nothing while the feed is empty.
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
        {entries.map((entry) => (
          <Line entry={entry} key={entry.id} shell={shell} />
        ))}
      </ol>
    </section>
  )
}

function Line({ entry, shell }: { entry: FeedEntry; shell: ShellApi }) {
  return (
    <li data-kind={entry.kind}>
      <time dateTime={new Date(entry.at).toISOString()}>{time(entry.at)}</time>
      <p>{entry.text}</p>
      {entry.actions?.map((action) => (
        <button className="agent-feed-action" key={action.label} onClick={() => shell.openArtifact(action.artifact, action.params)} type="button">
          {action.label}
        </button>
      ))}
    </li>
  )
}
