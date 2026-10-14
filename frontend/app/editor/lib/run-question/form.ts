import { BUILDING_TYPES } from '@/lib/building-types'
import type { RunQuestion } from '@/lib/orchestrator-runs/types'

import { asksForLot } from './lots'

/**
 * What a waiting run asks, as something to answer: a district lot (pick one Law read), an intent to reconfirm, fields
 * to fill (용도, 기준일, 시설면적, 주차 대수), or a wait on an external host that nobody answers here.
 */
export type QuestionShape = 'lot' | 'intent' | 'fields' | 'conversation' | 'external'

/** Answers that are whole documents (a program, an elevation or design brief): written through the conversation. */
const DOCUMENT_FIELDS = new Set(['program', 'elevation', 'design', 'kmass_design'])

export function shapeOf(question: RunQuestion): QuestionShape {
  if (asksForLot(question)) return 'lot'
  if (question.kind === 'mass_external') return 'external'
  if (question.fields.includes('confirm') && question.fields.includes('context_hash')) return 'intent'
  if (question.fields.some((field) => DOCUMENT_FIELDS.has(field))) return 'conversation'
  return 'fields'
}

/** One card per question, not per run: a run that answers and asks again gets a fresh card. */
export function questionKey(runId: string, question: RunQuestion | null | undefined): string {
  return `${runId}:${question?.kind ?? ''}:${question?.code ?? ''}:${(question?.fields ?? []).join(',')}:${String(question?.context_hash ?? '')}`
}

export interface FieldSpec {
  name: string
  label: string
  input: 'select' | 'date' | 'number' | 'integer' | 'text'
  options?: readonly string[]
  unit?: string
  /** What the owner said about this field (Law's parking rule and count), in words. */
  hint?: string
}

const record = (value: unknown): Record<string, unknown> => (value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {})

/** Law's parking reasons as one line: the rule and article, the count it reached, or why it reached none. */
function parkingHint(question: RunQuestion): string | undefined {
  const law = record((question as unknown as Record<string, unknown>).law_parking)
  const parts = [
    typeof law.rule === 'string' && law.rule ? law.rule : null,
    typeof law.article === 'string' && law.article ? law.article : null,
    typeof law.required_cars === 'number' ? `법정 ${law.required_cars}대` : null,
  ].filter(Boolean)
  return parts.length ? `법규 근거: ${parts.join(' · ')}` : '법규에서 쓸 수 있는 주차 대수를 받지 못했어요. 근거가 있는 대수를 넣어 주세요.'
}

/** The fields a run asks for, each with its label, input and unit; a field this screen has no word for is plain text. */
export function fieldsOf(question: RunQuestion): FieldSpec[] {
  return question.fields.map((name): FieldSpec => {
    switch (name) {
      case 'building_type':
        return { name, label: '용도', input: 'select', options: BUILDING_TYPES }
      case 'assessment_date':
        return { name, label: '기준일', input: 'date' }
      case 'floor_area_m2':
        return { name, label: '시설면적', input: 'number', unit: '㎡' }
      case 'parking':
        return { name, label: '주차 대수', input: 'integer', unit: '대', hint: parkingHint(question) }
      default:
        return { name, label: '필요한 값', input: 'text' }
    }
  })
}

/** The typed answer for the owner, or why it cannot be sent yet. */
export function answerOf(fields: readonly FieldSpec[], values: Readonly<Record<string, string>>): { input: Record<string, string | number> } | { missing: string } {
  const input: Record<string, string | number> = {}
  for (const field of fields) {
    const raw = (values[field.name] ?? '').trim()
    if (!raw) return { missing: field.label }
    if (field.input === 'number' || field.input === 'integer') {
      const value = Number(raw)
      if (!Number.isFinite(value) || value < 0 || (field.input === 'integer' && !Number.isInteger(value)) || (field.input === 'number' && value <= 0)) return { missing: field.label }
      input[field.name] = value
    } else {
      input[field.name] = raw
    }
  }
  return { input }
}

/** The person's answer as their line in the thread ("용도: 업무시설 · 기준일: 2026-10-13"). */
export function answerLine(fields: readonly FieldSpec[], input: Readonly<Record<string, string | number>>): string {
  return fields.map((field) => `${field.label}: ${input[field.name]}${field.unit ?? ''}`).join(' · ')
}

/** An intent to reconfirm, in words: each declared part that has a value ("파르티: 마당 중심 …"). */
const INTENT_LABELS: Record<string, string> = {
  parti: '파르티', ordering_principles: '질서 원리', massing_strategy: '매스 전략', non_negotiables: '양보할 수 없는 것',
  precedents: '참고 사례', material_attitude: '재료 태도', rejected_alternatives: '버린 대안',
}
export function intentLines(question: RunQuestion): string[] {
  const proposed = record((question as unknown as Record<string, unknown>).proposed_intent)
  return Object.entries(proposed).flatMap(([key, value]) => {
    const label = INTENT_LABELS[key]
    if (!label || value === null || value === undefined || value === '') return []
    const text = typeof value === 'string' ? value : Array.isArray(value) ? value.filter((item) => typeof item === 'string').join(', ') : ''
    return text ? [`${label}: ${text}`] : []
  })
}

/** Why the owner refused an answer: its own sentence for the person (`answer_rejected: …`), shown as it is; the editor
 * never translates the owner's wording, so without one it says only that the answer was not taken. */
export function rejectionText(detail: string | null | undefined): string {
  const message = (detail ?? '').startsWith('answer_rejected:') ? (detail ?? '').slice('answer_rejected:'.length).trim() : ''
  return message || '답을 보내지 못했어요. 값을 확인하고 다시 보내 주세요.'
}
