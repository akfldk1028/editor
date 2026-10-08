import { Check, CircleDashed, ExternalLink, X } from 'lucide-react'

import type { FeedCard as Card } from '@/lib/orchestrator-runs/feed'

import './feed-card.css'

/**
 * Structured content under a feed line, shaped after the agent that answered: Law's stat tiles
 * (value + where it comes from), Site's eight-fact checklist, Revision's findings table, the
 * ordinance sources as links, codes as chips. Shared by the conversation and the feed strip.
 */
export function FeedCard({ card }: { card: Card }) {
  switch (card.type) {
    case 'stats':
      return (
        <dl className="agent-stats">
          {card.items.map((item) => (
            <div key={item.label}>
              <dt>{item.label}</dt>
              <dd>{item.value}</dd>
              {item.hint && <small>{item.hint}</small>}
            </div>
          ))}
        </dl>
      )
    case 'chips':
      return <ul className="agent-chips">{card.items.map((item) => <li key={item}>{item}</li>)}</ul>
    case 'checks':
      return (
        <ul className="agent-checks">
          {card.items.map((item) => (
            <li data-critical={item.critical ? 'true' : undefined} data-state={item.state} key={item.label}>
              <span aria-hidden="true" className="agent-check-mark">
                {item.state === 'ok' ? <Check size={11} /> : item.state === 'missing' ? <X size={11} /> : <CircleDashed size={11} />}
              </span>
              <b>{item.label}</b>
              {item.note && <small>{item.note}</small>}
            </li>
          ))}
        </ul>
      )
    case 'findings':
      return (
        <ol className="agent-findings">
          {card.items.map((item, index) => (
            <li key={`${item.title}-${index}`}>
              <b>{item.title}</b>
              <small>{item.by} 제기 · {item.category}{item.owners ? ` · 담당 ${item.owners}` : ''}</small>
              <p>→ {item.action}</p>
            </li>
          ))}
        </ol>
      )
    case 'links':
      return (
        <ul className="agent-links">
          {card.items.map((item, index) => (
            <li key={`${item.label}-${index}`}>
              {item.href ? (
                <a href={item.href} rel="noopener" target="_blank">{item.label}<ExternalLink aria-hidden="true" size={11} /></a>
              ) : (
                <span>{item.label}</span>
              )}
              {item.note && <small>{item.note}</small>}
            </li>
          ))}
        </ul>
      )
  }
}
