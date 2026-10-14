'use client'

import { useState } from 'react'

import { RunRequestError, resumeRun } from '@/lib/orchestrator-runs/api'
import type { RunQuestion } from '@/lib/orchestrator-runs/types'

import { answerLine, answerOf, fieldsOf, intentLines, rejectionText, shapeOf } from '../form'
import { LotQuestion } from './LotQuestion'
import './run-question.css'

interface Props {
  projectId: string
  runId: string
  question: RunQuestion
  /** The answer in words, once the run took it (the card leaves when the run moves on). */
  onAnswered?(line: string): void
}

/** Whatever a waiting run asks, answered in place: a district lot, an intent to reconfirm, or fields to fill. */
export function QuestionCard(props: Props) {
  const shape = shapeOf(props.question)
  if (shape === 'lot') return <LotQuestion {...props} onAnswered={(lot) => props.onAnswered?.(`획지 선택: ${lot}`)} />
  if (shape === 'external') {
    return <p className="run-question-note" role="status">매스 생성 결과를 기다리고 있어요 — 외부 생성기가 결과를 넘기면 이어서 검토해요.</p>
  }
  if (shape === 'conversation') {
    return <p className="run-question-note" role="status">검토를 이어가려면 실 구성이나 설계 내용이 더 필요해요. 대화로 원하는 내용을 알려 주시면 정리해서 이어가요.</p>
  }
  return shape === 'intent' ? <IntentQuestion {...props} /> : <FieldsQuestion {...props} />
}

function useAnswer({ projectId, runId, onAnswered }: Props) {
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [answered, setAnswered] = useState<string | null>(null)
  const send = async (input: Record<string, unknown>, line: string) => {
    setSending(true)
    setError(null)
    try {
      await resumeRun(projectId, runId, input)
      setAnswered(line)
      onAnswered?.(line)
    } catch (failure) {
      setError(rejectionText(failure instanceof RunRequestError ? failure.detail : null))
    } finally {
      setSending(false)
    }
  }
  return { sending, error, answered, send }
}

function FieldsQuestion(props: Props) {
  const fields = fieldsOf(props.question)
  const [values, setValues] = useState<Record<string, string>>({})
  const [missing, setMissing] = useState<string | null>(null)
  const { sending, error, answered, send } = useAnswer(props)
  const submit = () => {
    const answer = answerOf(fields, values)
    if ('missing' in answer) { setMissing(answer.missing); return }
    setMissing(null)
    void send(answer.input, answerLine(fields, answer.input))
  }
  return (
    <section aria-label="검토에 필요한 값" className="run-question">
      <h3>검토를 이어가려면 값이 필요해요: {fields.map((field) => field.label).join(', ')}</h3>
      <form className="run-question-form" onSubmit={(event) => { event.preventDefault(); submit() }}>
        {fields.map((field) => (
          <label key={field.name}>
            <span>{field.label}</span>
            {field.input === 'select' ? (
              <select disabled={sending || !!answered} onChange={(event) => setValues({ ...values, [field.name]: event.target.value })} value={values[field.name] ?? ''}>
                <option value="">고르세요</option>
                {field.options?.map((option) => <option key={option} value={option}>{option}</option>)}
              </select>
            ) : (
              <span className="run-question-input">
                <input disabled={sending || !!answered} inputMode={field.input === 'text' || field.input === 'date' ? undefined : 'decimal'}
                  onChange={(event) => setValues({ ...values, [field.name]: event.target.value })}
                  type={field.input === 'date' ? 'date' : 'text'} value={values[field.name] ?? ''} />
                {field.unit && <small>{field.unit}</small>}
              </span>
            )}
            {field.hint && <small className="run-question-hint">{field.hint}</small>}
          </label>
        ))}
        <button className="artifact-primary" disabled={sending || !!answered} type="submit">{sending ? '보내는 중…' : '이 값으로 검토 이어가기'}</button>
      </form>
      {missing && <p className="run-question-note" data-kind="warn" role="alert">알맞게 채워 주세요: {missing}</p>}
      {answered && <p className="run-question-note" role="status">보냈어요 — 이어서 검토해요.</p>}
      {error && <p className="run-question-note" data-kind="warn" role="alert">{error}</p>}
    </section>
  )
}

function IntentQuestion(props: Props) {
  const lines = intentLines(props.question)
  const hash = (props.question as unknown as Record<string, unknown>).context_hash
  const { sending, error, answered, send } = useAnswer(props)
  return (
    <section aria-label="설계 의도 확인" className="run-question">
      <h3>요구나 대지 조건이 바뀌었어요. 이 설계 의도를 그대로 이어갈까요?</h3>
      {lines.length ? <ul className="run-question-list">{lines.map((line) => <li key={line}>{line}</li>)}</ul>
        : <p className="run-question-sub">확인할 설계 의도가 아직 비어 있어요.</p>}
      <p className="run-question-sub">고칠 부분이 있으면 대화로 말씀해 주세요. 이 확인은 형태나 법규 승인이 아니에요.</p>
      <button className="artifact-primary" disabled={sending || !!answered || typeof hash !== 'string'} onClick={() => void send({ confirm: true, context_hash: hash, intent: {} }, '설계 의도: 그대로 확인')} type="button">
        {sending ? '보내는 중…' : '이대로 확인'}
      </button>
      {answered && <p className="run-question-note" role="status">확인했어요 — 이어서 검토해요.</p>}
      {error && <p className="run-question-note" data-kind="warn" role="alert">{error}</p>}
    </section>
  )
}
