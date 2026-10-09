'use client'

import { useState } from 'react'
import type { DiscoveredOrdinance } from '../api/ordinances'
import { jurisdictionLine, LEVEL_LABEL, ordinanceLine, searchSummary } from '../lib/ordinances'
import { grouped, refLabel, type Review } from '../lib/review'
import type { OrdinanceState } from '../model/useOrdinances'

export type ReviewSelection =
  | { kind: 'item'; itemId: string; refIndex: number }
  | { kind: 'ordinance'; editionId: string; article: string | null }

const matchesSelection = (selected: ReviewSelection, ordinance: DiscoveredOrdinance) => selected.kind === 'ordinance' && selected.editionId === ordinance.edition_id

export function ReviewNavigation({ review, ordinances, selected, onSelect, onRetry }: { review: Review; ordinances: OrdinanceState; selected: ReviewSelection; onSelect(value: ReviewSelection): void; onRetry(): void }) {
  const [query, setQuery] = useState('')
  const matches = (value: string) => value.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())
  const seen = new Set<string>()
  const cited = review.items.flatMap(item => item.refs.flatMap((ref, refIndex) => {
    const key = JSON.stringify([ref.instrument, ref.article, ref.edition_id])
    if (ref.kind !== 'ordinance' || seen.has(key)) return []
    seen.add(key)
    return [{ item, ref, refIndex, key }]
  }))
  const groups = grouped(review).map(group => ({ ...group, items: group.items.filter(item => matches([item.title, ...item.refs.map(refLabel)].join(' '))) }))
  const found = ordinances.kind === 'ready' ? ordinances.data : null
  const listed = (found?.ordinances ?? []).filter(ordinance => matches(ordinance.name))
  const historical = (found?.historical ?? []).filter(ordinance => matches(ordinance.name))
  const nothingMatches = query && !groups.some(group => group.items.length) && !listed.length && !historical.length && !cited.some(({ ref }) => matches(refLabel(ref)))
  return (
    <nav className="law-reader-nav" aria-label="조항 목차">
      <input aria-label="조항·법령 검색" placeholder="조항·법령 이름 찾기" type="search" value={query} onChange={event => setQuery(event.target.value)} />
      <section aria-label="관할 조례">
        <h2>관할 조례 {found && <span>{found.ordinances.length}</span>}</h2>
        {ordinances.kind === 'loading' && <p className="law-reader-muted" role="status">법제처에서 관할 조례를 찾는 중…</p>}
        {ordinances.kind === 'error' && <p className="law-reader-muted" role="alert">{ordinances.text} <button type="button" className="law-reader-retry" onClick={onRetry}>다시 조회</button></p>}
        {found && <p className="law-reader-jurisdiction">{jurisdictionLine(found)}<br />{searchSummary(found)}{found.search.complete ? '' : ' — 목록이 완전하지 않을 수 있어요'}</p>}
        {found && found.jurisdiction.notes.map(note => <p className="law-reader-jurisdiction" key={note}>{note}</p>)}
        {found && found.jurisdiction.status === 'resolved' && !found.ordinances.length && <p className="law-reader-muted">관할 지자체의 조례를 찾지 못했어요. 조례가 없다는 뜻은 아니에요.</p>}
        {(['sigungu', 'sido'] as const).map(level => {
          const rows = listed.filter(ordinance => ordinance.level === level)
          if (!rows.length) return null
          const name = found?.jurisdiction.levels.find(candidate => candidate.level === level)?.name
          return <div key={level} className="law-reader-level">
            <h3>{LEVEL_LABEL[level]}{name ? ` · ${name}` : ''} <span>{rows.length}</span></h3>
            {rows.map(ordinance => (
              <button type="button" key={ordinance.edition_id} aria-current={matchesSelection(selected, ordinance) ? 'true' : undefined} data-relevance={ordinance.status.relevance}
                onClick={() => onSelect({ kind: 'ordinance', editionId: ordinance.edition_id, article: ordinance.review_refs.find(ref => ref.article)?.article ?? null })}>
                {ordinance.name}<small>{ordinanceLine(ordinance)}</small>
              </button>
            ))}
          </div>
        })}
        {historical.length > 0 && <details className="law-reader-excluded">
          <summary>연혁에만 있는 조례 {historical.length}건 — 기준일 당시 효력은 미확인</summary>
          {historical.map(ordinance => (
            <button type="button" key={ordinance.edition_id} aria-current={matchesSelection(selected, ordinance) ? 'true' : undefined} data-relevance={ordinance.status.relevance}
              onClick={() => onSelect({ kind: 'ordinance', editionId: ordinance.edition_id, article: ordinance.review_refs.find(ref => ref.article)?.article ?? null })}>
              {ordinance.name}<small>{ordinanceLine(ordinance)}</small>
            </button>
          ))}
        </details>}
        {found && (found.excluded_total ?? found.excluded.length) > 0 && <details className="law-reader-excluded">
          <summary>제외 {found.excluded_total ?? found.excluded.length}건 — 다른 지자체 이름 일치·기준일 뒤 시행</summary>
          <ul>{found.excluded.map(row => <li key={`${row.issuer}|${row.name}`}>{row.name} <span>{row.issuer} · {row.reason === 'jurisdiction_mismatch' ? '관할 아님' : `시행 ${row.first_effective_date ?? '예정'}`}</span></li>)}</ul>
          {(found.excluded_total ?? 0) > found.excluded.length && <p>… 외 {(found.excluded_total ?? 0) - found.excluded.length}건은 표시하지 않았어요</p>}
        </details>}
        {!found && cited.length > 0 && <div className="law-reader-level">
          <h3>검토가 인용한 조례 <span>{cited.length}</span></h3>
          {cited.filter(({ ref }) => matches(refLabel(ref))).map(({ item, ref, refIndex, key }) => (
            <button type="button" key={key} aria-current={selected.kind === 'item' && selected.itemId === item.id && selected.refIndex === refIndex ? 'true' : undefined} onClick={() => onSelect({ kind: 'item', itemId: item.id, refIndex })}>
              {refLabel(ref)}{!ref.article && <small>조례 전체 보기</small>}
            </button>
          ))}
        </div>}
        {!found && !cited.length && ordinances.kind !== 'loading' && <p className="law-reader-muted">조례 근거가 아직 확보되지 않았습니다.</p>}
      </section>
      {groups.filter(group => group.items.length).map(group => <section key={group.id} aria-label={group.label}>
        <h2>{group.label} <span>{group.items.length}</span></h2>
        {group.items.map(item => <button type="button" key={item.id} aria-current={selected.kind === 'item' && selected.itemId === item.id ? 'true' : undefined} onClick={() => onSelect({ kind: 'item', itemId: item.id, refIndex: 0 })}>
          {item.title}
        </button>)}
      </section>)}
      {nothingMatches && <p className="law-reader-muted">일치하는 조항이 없습니다.</p>}
    </nav>
  )
}
