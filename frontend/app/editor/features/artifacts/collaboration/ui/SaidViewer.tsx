'use client'

import { ChevronLeft, ChevronRight } from 'lucide-react'
import { type MouseEvent, useMemo, useState } from 'react'

import type { SaidItem } from '../lib/graph'

/** The recorded text as it is, JSON indented; parsed only when a card is opened. */
function Recorded({ text, words }: { text: string; words: string }) {
  const shown = useMemo(() => {
    try { return JSON.stringify(JSON.parse(text), null, 2) } catch { return text }
  }, [text])
  if (!shown.trim() || shown.trim() === words.trim()) return null
  return (
    <>
      <small className="collab-said-caption">기록 원문 · {text.length.toLocaleString('ko-KR')}자</small>
      <pre className="collab-said-raw">{shown}</pre>
    </>
  )
}

interface Props {
  items: readonly SaidItem[]
  open: boolean
  onToggle: () => void
}

/**
 * The messages on one card, one at a time: which call it was, its gist (or all of it when opened), and ‹ n/m › to step
 * through the others. It opens on the latest; a new message moves it there unless the reader stepped back.
 */
export function SaidViewer({ items, open, onToggle }: Props) {
  const [picked, setPicked] = useState<number | null>(null)
  if (!items.length) return null
  const at = picked === null ? items.length - 1 : Math.min(picked, items.length - 1)
  const item = items[at]!
  const more = item.full.length > item.text.length || item.full.includes('\n') || (!!item.raw.trim() && item.raw.trim() !== item.text.trim())
  // The card itself selects its agent on click; its own buttons must not.
  const step = (event: MouseEvent, to: number) => { event.stopPropagation(); setPicked(to >= items.length - 1 ? null : to) }
  return (
    <>
      <small className="collab-said-caption" title={item.caption}>{item.caption}</small>
      {open ? (
        <div className="collab-said-open">
          <p className="collab-said-full">{item.full}</p>
          <Recorded text={item.raw} words={item.full} />
        </div>
      ) : item.text ? <p>{item.text}</p> : null}
      {(items.length > 1 || more) && (
        <div className="collab-said-bar nodrag">
          {items.length > 1 && (
            <span className="collab-said-step">
              <button aria-label="이전 메시지" disabled={at === 0} onClick={(event) => step(event, at - 1)} type="button"><ChevronLeft aria-hidden="true" size={12} /></button>
              <span aria-live="polite">{at + 1}/{items.length}</span>
              <button aria-label="다음 메시지" disabled={at === items.length - 1} onClick={(event) => step(event, at + 1)} type="button"><ChevronRight aria-hidden="true" size={12} /></button>
            </span>
          )}
          {more && (
            <button aria-expanded={open} className="collab-said-toggle" onClick={(event) => { event.stopPropagation(); onToggle() }} type="button">
              {open ? '접기 ▲' : '전체 보기 ▼'}
            </button>
          )}
        </div>
      )}
    </>
  )
}
