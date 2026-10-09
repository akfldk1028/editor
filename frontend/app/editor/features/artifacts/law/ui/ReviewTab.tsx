'use client'

import { ChevronDown, ExternalLink, MessageSquare } from 'lucide-react'
import { useState } from 'react'

import { sendCommand } from '@/lib/orchestrator-runs/commands'

import type { LawAnalysis } from '../api/analyze'
import { clauseContext, grouped, KIND_LABEL, refLabel, type Review, type ReviewItem, STATUS_LABEL, statusCounts, ymd } from '../lib/review'

interface Site { pnu: string; address?: string; assessmentDate: string }

const DEFAULT_QUESTION = '이 대지에서 이 조항은 어떻게 적용되나요?'

/**
 * 검토 조항: every provision the Law Agent listed for this lot, by group — what it is, why this lot meets it, its
 * status as the Law Agent gave it. Opening an item shows the article texts, source, edition and the linked
 * act/decree/ordinance; 이 조항 질문하기 sends the item with the lot and date to the conversation, where the
 * Orchestrator asks the Law Agent about exactly it. Missing material is shown as missing, never as "no law".
 */
export function ReviewTab({ analysis, site }: { analysis: LawAnalysis; site: Site }) {
  const review = (analysis as LawAnalysis & { review?: Review }).review
  const [open, setOpen] = useState<string | null>(null)
  if (!review) {
    return <p className="law-note">이 분석에는 검토 조항 목록이 없어요 — 다시 분석하면 Law Agent가 조항별로 정리해 보내요.</p>
  }
  const counts = statusCounts(review)
  return (
    <div className="law-review">
      <p className="law-review-head">
        <strong>검토 조항 {review.items.length}개</strong>
        {review.assessment_date && <span>기준일 {review.assessment_date}</span>}
        {counts.map(({ status, count }) => <span className="law-status" data-status={status} key={status}>{STATUS_LABEL[status]} {count}</span>)}
      </p>
      {review.search.connected === false && (
        <p className="law-note" data-kind="notice">조문 검색에서 원문을 받지 못했어요 ({review.search.errors.join(' / ') || '응답 없음'}) — 법규가 없다는 뜻이 아니에요.</p>
      )}
      {grouped(review).map((group) => (
        <section aria-label={group.label} className="law-review-group" key={group.id}>
          <h2>{group.label} <small>{group.items.length}</small></h2>
          <ul>
            {group.items.map((item) => (
              <ReviewRow item={item} key={item.id} onToggle={() => setOpen(open === item.id ? null : item.id)} open={open === item.id} site={site} />
            ))}
          </ul>
        </section>
      ))}
      {review.gaps.length > 0 && (
        <section aria-label="자료 확보 필요" className="law-review-group" data-kind="gaps">
          <h2>자료 확보 필요 <small>{review.gaps.length}</small></h2>
          <ul className="law-list">{review.gaps.map((gap) => <li key={`${gap.item}-${gap.what}`}>{gap.what}</li>)}</ul>
        </section>
      )}
    </div>
  )
}

function ReviewRow({ item, open, onToggle, site }: { item: ReviewItem; open: boolean; onToggle: () => void; site: Site }) {
  const [question, setQuestion] = useState(DEFAULT_QUESTION)
  const [asked, setAsked] = useState(false)
  const lead = item.refs.find((ref) => ref.article) ?? item.refs[0]
  const ask = () => {
    const text = question.trim() || DEFAULT_QUESTION
    sendCommand({ kind: 'ask', text, role: 'law', clause: clauseContext(item), site: { pnu: site.pnu, address: site.address, assessmentDate: site.assessmentDate } })
    setAsked(true)
  }
  return (
    <li className="law-review-item" data-open={open || undefined}>
      <button aria-expanded={open} className="law-review-row" onClick={onToggle} type="button">
        <span className="law-review-title">
          <b>{item.title}</b>
          {lead && <small>{refLabel(lead)}{item.refs.length > 1 ? ` 외 ${item.refs.length - 1}` : ''}</small>}
        </span>
        <span className="law-review-why">{item.reason}</span>
        <span className="law-status" data-status={item.status}>{STATUS_LABEL[item.status]}{item.value ? ` · ${item.value}` : ''}</span>
        <ChevronDown aria-hidden="true" className="law-review-chevron" size={14} />
      </button>
      {open && (
        <div className="law-review-detail">
          {item.basis && <p className="law-review-basis"><span>판단 근거</span>{item.basis}</p>}
          <ol className="law-review-refs">
            {item.refs.map((ref) => (
              <li key={`${ref.instrument}-${ref.article}-${ref.clause}`}>
                <p className="law-review-ref">
                  <b>{refLabel(ref)}</b>
                  <span className="law-badge">{KIND_LABEL[ref.kind]}</span>
                  {ref.edition_id && <small>판본 {ref.edition_id}</small>}
                  {ref.effective_date && <small>시행 {ymd(ref.effective_date)}</small>}
                  {ref.url && <a href={ref.url} rel="noreferrer" target="_blank">law.go.kr <ExternalLink aria-hidden="true" size={11} /></a>}
                </p>
                {ref.text ? <blockquote>{ref.text}</blockquote> : <p className="law-review-gap">원문 자료 확보 필요 — {ref.text_gap ?? '원문을 받지 못했어요'}</p>}
              </li>
            ))}
            {item.refs.length === 0 && <li><p className="law-review-gap">근거 조문 자료 확보 필요</p></li>}
          </ol>
          <div className="law-review-ask">
            <input aria-label="이 조항에 대한 질문" onChange={(event) => setQuestion(event.target.value)} value={question} />
            <button className="artifact-primary" onClick={ask} type="button"><MessageSquare aria-hidden="true" size={12} /><span>이 조항 질문하기</span></button>
          </div>
          {asked && <p className="law-note">대화창에서 Orchestrator Agent가 Law Agent에게 이 조항을 묻고 있어요 (PNU {site.pnu} · 기준일 {site.assessmentDate}).</p>}
        </div>
      )}
    </li>
  )
}
