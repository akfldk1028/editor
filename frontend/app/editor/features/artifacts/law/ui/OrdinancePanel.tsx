'use client'

import { useState } from 'react'
import type { ReferenceSite } from '../api/reference'
import { refLabel, type Review } from '../lib/review'
import { SourceArticle } from './SourceArticle'

export function OrdinancePanel({ review, site }: { review: Review; site: ReferenceSite }) {
  const [opened, setOpened] = useState<Record<string, boolean>>({})
  const references = [...new Map(review.items.flatMap(item => item.refs).filter(ref => ref.kind === 'ordinance')
    .map(ref => [JSON.stringify([ref.instrument, ref.article, ref.edition_id]), ref])).entries()]
  return (
    <section className="law-ordinances" aria-label="관할 조례">
      <header><h2>관할 조례 <small>검토 근거 {references.length}건</small></h2></header>
      {references.length === 0 && <p className="law-review-gap">관할 조례 목록을 아직 받지 못했습니다. 조례가 적용되지 않는다는 뜻은 아닙니다.</p>}
      {references.map(([key, ref]) => <details className="law-ordinance-entry" key={key} onToggle={event => { const open = event.currentTarget.open; setOpened(current => ({ ...current, [key]: open })) }}>
        <summary><span>{refLabel(ref)}</span>{!ref.article && <small>조문 특정 필요</small>}</summary>
        {opened[key] && <SourceArticle reference={ref} site={site} />}
      </details>)}
    </section>
  )
}
