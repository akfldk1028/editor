'use client'

import { useState } from 'react'

import { RunRequestError, resumeRun } from '@/lib/orchestrator-runs/api'
import type { RunQuestion } from '@/lib/orchestrator-runs/types'

import { rejectionText } from '../form'
import { lotChoices } from '../lots'
import './run-question.css'

interface Props {
  projectId: string
  runId: string
  question: RunQuestion
  /** The lot chosen, once the run took it (the card itself leaves when the run moves on). */
  onAnswered?(lot: string): void
}

/**
 * The run asks which district lot (획지) this parcel is: the plan's documents do not tie the parcel to one. Each lot
 * Law read is a card with what Law quoted for it, as quoted; choosing one answers the run, which continues with
 * that lot's rules on the person's word.
 */
export function LotQuestion({ projectId, runId, question, onAnswered }: Props) {
  const [sending, setSending] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [answered, setAnswered] = useState<string | null>(null)
  const choices = lotChoices(question)
  const choose = async (lot: string) => {
    setSending(lot)
    setError(null)
    try {
      await resumeRun(projectId, runId, { district_lot: lot })
      setAnswered(lot)
      onAnswered?.(lot)
    } catch (failure) {
      setError(rejectionText(failure instanceof RunRequestError ? failure.detail : null))
    } finally {
      setSending(null)
    }
  }
  return (
    <section aria-label="획지 선택" className="run-question">
      <h3>이 필지는 지구단위계획구역 안이에요. 어느 획지인가요?</h3>
      <p className="run-question-sub">고시 문서에 이 필지가 어느 획지인지 적혀 있지 않아요. 분양 공고나 토지 서류에서 확인한 획지를 골라 주시면, 그 획지의 규정으로 검토를 이어가요.</p>
      <div className="run-question-lots">
        {choices.map((choice) => (
          <article className="run-question-lot" key={choice.lot}>
            <header>
              <strong>{choice.lot}</strong>
              {choice.basis?.quote && (
                <details>
                  <summary>획지 근거</summary>
                  {choice.basis.source && <small>{choice.basis.source}</small>}
                  <blockquote>{choice.basis.quote}</blockquote>
                </details>
              )}
            </header>
            <dl>
              {choice.rows.map((row) => (
                <div key={row.label}>
                  <dt>{row.label}</dt>
                  <dd>
                    {row.values.map((value, index) => (
                      <span key={index}>
                        {value.text}
                        {(value.quote || value.source) && (
                          <details>
                            <summary>근거</summary>
                            {value.source && <small>{value.source}</small>}
                            {value.quote && <blockquote>{value.quote}</blockquote>}
                          </details>
                        )}
                      </span>
                    ))}
                  </dd>
                </div>
              ))}
            </dl>
            {choice.others > 0 && <p className="run-question-sub">그 밖에 읽은 항목 {choice.others}개</p>}
            <button className="artifact-primary" disabled={sending !== null || answered !== null} onClick={() => void choose(choice.lot)} type="button">
              {sending === choice.lot ? '보내는 중…' : '이 획지로 검토 이어가기'}
            </button>
          </article>
        ))}
      </div>
      {answered && <p className="run-question-note" role="status">{answered}(으)로 답했어요 — 그 획지의 규정으로 검토를 이어가요.</p>}
      {error && <p className="run-question-note" data-kind="warn" role="alert">{error}</p>}
    </section>
  )
}
