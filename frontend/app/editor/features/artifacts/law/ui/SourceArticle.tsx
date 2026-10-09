'use client'

import { ExternalLink, RotateCcw } from 'lucide-react'
import { useEffect, useState } from 'react'
import { type ReferenceSite, type ReferenceText } from '../api/reference'
import { loadCachedReference } from '../api/reference-cache'
import { sourceLink } from '../lib/source-link'
import { KIND_LABEL, refLabel, type ReviewRef, ymd } from '../lib/review'
import { sourceParagraphs, sourceUnit } from '../lib/source-text'

export function SourceArticle({ reference, site }: { reference: ReviewRef; site: ReferenceSite }) {
  const [attempt, retry] = useState(0)
  const [state, setState] = useState<{ loading: boolean; data?: ReferenceText; error?: string }>({ loading: true })
  const identity = JSON.stringify([reference, site])
  useEffect(() => {
    const controller = new AbortController()
    const [ref, target] = JSON.parse(identity) as [ReviewRef, ReferenceSite]
    setState({ loading: true })
    void loadCachedReference(ref, target, attempt > 0).then(data => {
      if (!controller.signal.aborted) setState({ loading: false, data })
    }).catch(error => {
      if (!controller.signal.aborted) setState({ loading: false, error: error instanceof Error ? error.message : '원문 조회 실패' })
    })
    return () => controller.abort()
  }, [identity, attempt])
  const text = state.data?.text ?? reference.text
  const link = sourceLink(reference, state.data)
  return (
    <article className="law-source" aria-busy={state.loading}>
      <header className="law-source-heading">
        <span className="law-source-kind" data-kind={reference.kind}>{KIND_LABEL[reference.kind]}</span>
        <h3>{refLabel(reference)}</h3>
        <a href={link.url} target="_blank" rel="noreferrer">{link.label} <ExternalLink size={13} aria-hidden="true" /></a>
      </header>
      <p className="law-source-meta">
        <span>기준일 {site.assessmentDate}</span>
        {(state.data?.edition ?? reference.edition_id) && <span>판본 {state.data?.edition ?? reference.edition_id}</span>}
        {(state.data?.effective ?? reference.effective_date) && <span>시행 {ymd(state.data?.effective ?? reference.effective_date)}</span>}
      </p>
      <p className="law-source-meta"><a href={link.url} target="_blank" rel="noreferrer" style={{ overflowWrap: 'anywhere' }}>{decodeURI(link.url)}</a></p>
      {reference.edition_id && state.data?.edition && reference.edition_id !== state.data.edition && <p className="law-source-notice">검토에 사용된 판본({reference.edition_id})과 조회된 판본({state.data.edition})이 다릅니다. 아래 원문을 기존 판단의 동일 근거로 확정할 수 없습니다.</p>}
      {state.loading && <p className="law-source-notice" role="status">조문 원문을 불러오고 있습니다…</p>}
      {state.error && <div className="law-source-notice"><p>{state.error}</p><button onClick={() => retry(value => value + 1)} type="button"><RotateCcw size={13} aria-hidden="true" />원문 다시 조회</button></div>}
      {text && <><p className="law-source-caption">{state.data ? '조회한 조문 원문' : '검토 시 수집한 본문 · 전체 조문 조회 전'}</p><div className="law-source-text">{sourceParagraphs(text).map((part, index) => <p key={index} data-unit={sourceUnit(part)}>{part}</p>)}</div></>}
      {state.data?.annexes && state.data.annexes.length > 0 && <section className="law-source-annexes" aria-label="별표">
        <p className="law-source-caption">별표 {state.data.annexes.length}건</p>
        <ul>{state.data.annexes.map((annex, index) => <li key={`${annex.number ?? index}-${annex.title}`}>
          {annex.file_url ? <a href={annex.file_url} target="_blank" rel="noreferrer">{annex.title}</a> : annex.title}
          {annex.kind && <span> · {annex.kind}</span>}{annex.file_kind && <span> · {annex.file_kind}</span>}
          {annex.content && <div className="law-source-text">{sourceParagraphs(annex.content).map((part, line) => <p key={line} data-unit={sourceUnit(part)}>{part}</p>)}</div>}
        </li>)}</ul>
      </section>}
      {!reference.article && !text && state.data?.url && <p className="law-source-notice">조회한 판본의 전체 조문을 공식 원문에서 볼 수 있습니다. <a href={state.data.url} target="_blank" rel="noreferrer">공식 원문에서 전체 조문 보기</a></p>}
      {!text && !state.loading && !state.data?.url && !state.error && <p className="law-review-gap">{reference.text_gap || '원문 자료 확보 필요'}</p>}
    </article>
  )
}

