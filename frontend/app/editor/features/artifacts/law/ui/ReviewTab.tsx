'use client'

import { useEffect, useRef, useState, type CSSProperties } from 'react'
import type { LawAnalysis } from '../api/analyze'
import type { ReferenceSite } from '../api/reference'
import { articlesOf, toReviewItem, toReviewRef } from '../lib/ordinances'
import { KIND_LABEL, type Review } from '../lib/review'
import { useOrdinances } from '../model/useOrdinances'
import { OrdinanceReadings } from './OrdinanceReadings'
import { SourceArticle } from './SourceArticle'
import { ReviewNavigation, type ReviewSelection } from './ReviewNavigation'
import { ReviewContext } from './ReviewContext'
import './review-reader.css'

export function ReviewTab({ analysis, site }: { analysis: LawAnalysis; site: ReferenceSite }) {
  const review = (analysis as LawAnalysis & { review?: Review }).review
  if (!review) return <p className="law-note">검토 조항 목록을 받지 못했습니다. 새로고침으로 다시 조회해 주세요.</p>
  return <>
    <ReviewReader review={review} site={site} key={`${site.pnu}|${site.assessmentDate}`} />
    <OrdinanceReadings analysis={analysis} />
  </>
}

function ReviewReader({ review, site }: { review: Review; site: ReferenceSite }) {
  const root = useRef<HTMLDivElement>(null)
  const [wide, setWide] = useState(false)
  const [navigationOpen, setNavigationOpen] = useState(false)
  const [contextOpen, setContextOpen] = useState(false)
  const [selection, setSelection] = useState<ReviewSelection | null>(null)
  const [fontSize, setFontSize] = useState(13)
  const [refresh, setRefresh] = useState(0)
  const ordinances = useOrdinances(review, site, refresh)
  useEffect(() => {
    const element = root.current
    if (!element) return
    const observer = new ResizeObserver(([entry]) => setWide((entry?.contentRect.width ?? 0) >= 960))
    observer.observe(element)
    return () => observer.disconnect()
  }, [])
  const found = ordinances.kind === 'ready' ? [...ordinances.data.ordinances, ...(ordinances.data.historical ?? [])] : []
  const chosen = selection?.kind === 'ordinance' ? found.find(candidate => candidate.edition_id === selection.editionId) : undefined
  const itemSelection = selection?.kind === 'item' ? selection : null
  const reviewItem = review.items.find(candidate => candidate.id === itemSelection?.itemId) ?? review.items.find(candidate => candidate.refs.some(ref => ref.kind === 'ordinance')) ?? review.items[0]
  const refIndex = reviewItem && itemSelection && reviewItem.id === itemSelection.itemId && reviewItem.refs[itemSelection.refIndex] ? itemSelection.refIndex : Math.max(0, reviewItem?.refs.findIndex(ref => ref.kind === 'ordinance') ?? 0)
  const article = chosen && selection?.kind === 'ordinance' ? selection.article : null
  const item = chosen ? toReviewItem(chosen, article) : reviewItem
  const reference = chosen ? toReviewRef(chosen, article) : reviewItem?.refs[refIndex]
  const current: ReviewSelection = chosen && selection ? selection : { kind: 'item', itemId: reviewItem?.id ?? '', refIndex }
  const select = (value: ReviewSelection) => { setSelection(value); setNavigationOpen(false) }
  return <div className="law-reader" data-wide={wide} ref={root} style={{ '--law-reader-size': `${fontSize}px` } as CSSProperties}>
    <header className="law-reader-head"><h1>대지 법규 검토</h1><p>검토 {review.items.length}개 · 기준일 {site.assessmentDate}</p></header>
    {!item ? <p className="law-note">검토 목록이 비어 있습니다. 법규가 없다는 뜻은 아닙니다.</p> : <div className="law-reader-layout">
      <details className="law-reader-disclosure" open={wide || navigationOpen} onToggle={event => { if (!wide) setNavigationOpen(event.currentTarget.open) }}>
        <summary>관할 조례 · 조항 목차 <span>{item.title}</span></summary>
        <ReviewNavigation review={review} ordinances={ordinances} selected={current} onSelect={select} onRetry={() => setRefresh(value => value + 1)} />
      </details>
      <section className="law-reader-paper" aria-label="조문 원문">
        <header className="law-reader-toolbar"><strong>{item.title}</strong><div className="law-reader-font"><span>글자</span><button aria-label="원문 글자 작게" disabled={fontSize <= 12} onClick={() => setFontSize(value => value - 1)} type="button">−</button><output aria-label="원문 글자 크기">{fontSize}</output><button aria-label="원문 글자 크게" disabled={fontSize >= 22} onClick={() => setFontSize(value => value + 1)} type="button">+</button></div></header>
        {chosen ? (
          <nav className="law-reader-refnav" aria-label="조문 선택">
            <button type="button" aria-pressed={article === null} onClick={() => setSelection({ kind: 'ordinance', editionId: chosen.edition_id, article: null })}>조례 전체 · 공식 원문</button>
            {articlesOf(chosen).map(candidate => <button type="button" key={candidate} aria-pressed={article === candidate} onClick={() => setSelection({ kind: 'ordinance', editionId: chosen.edition_id, article: candidate })}>{candidate}</button>)}
          </nav>
        ) : (
          <nav className="law-reader-refnav" aria-label="근거 법령 선택">{item.refs.map((ref, index) => <button type="button" key={JSON.stringify([ref.instrument, ref.article, ref.clause])} title={ref.instrument} aria-pressed={index === refIndex} onClick={() => setSelection({ kind: 'item', itemId: item.id, refIndex: index })}>{KIND_LABEL[ref.kind]} · {ref.article || (ref.kind === 'ordinance' ? '전체 조례' : '조문 확인 필요')}</button>)}</nav>
        )}
        {chosen?.status.in_force === 'unknown' && <p className="law-source-notice" role="note">연혁 목록에만 있는 조례예요. 현행 목록에 없고 폐지 시점도 목록으로는 알 수 없어서, 기준일 {site.assessmentDate}에 효력이 있었는지는 확인되지 않았어요.</p>}
        {reference ? <SourceArticle key={JSON.stringify([reference, site])} reference={reference} site={site} /> : <p className="law-reader-muted">근거 조문 자료 확보 필요</p>}
      </section>
      {chosen ? <div /> : <details className="law-reader-disclosure" open={wide || contextOpen} onToggle={event => { if (!wide) setContextOpen(event.currentTarget.open) }}>
        <summary>관련 내용 · 근거</summary>
        <ReviewContext key={JSON.stringify([item.id, refIndex, site])} item={item} />
      </details>}
    </div>}
    <details className="law-reader-gaps"><summary>추가 검토 사항 {review.gaps.length}건</summary>{review.search.connected === false && <p>조문 검색 연결 확인 필요: {review.search.errors.join(' / ') || '응답 없음'}</p>}<ul>{review.gaps.map((gap, index) => <li key={`${gap.item}-${index}`}>{gap.what}</li>)}</ul></details>
  </div>
}
