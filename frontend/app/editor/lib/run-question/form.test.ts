import { expect, test } from 'bun:test'
import type { RunQuestion } from '@/lib/orchestrator-runs/types'
import { answerLine, answerOf, fieldsOf, intentLines, questionKey, rejectionText, shapeOf } from './form'

test('each question has its shape: a lot, an intent to reconfirm, fields, or an external wait', () => {
  expect(shapeOf({ kind: 'request_input', fields: ['district_lot'], candidates: { lots: [{ lot: 'A11' }] } })).toBe('lot')
  expect(shapeOf({ kind: 'request_input', fields: ['confirm', 'context_hash', 'intent'] })).toBe('intent')
  expect(shapeOf({ kind: 'mass_external', fields: ['ready'] })).toBe('external')
  expect(shapeOf({ kind: 'request_input', fields: ['building_type', 'assessment_date'] })).toBe('fields')
  // A whole document (a program, a design brief) is not typed into a box: it is written through the conversation.
  expect(shapeOf({ kind: 'request_input', fields: ['program'] })).toBe('conversation')
})

test('a run that answers and asks again gets a new card, the same question keeps its card', () => {
  const lot: RunQuestion = { kind: 'request_input', code: 'district_lot_required', fields: ['district_lot'] }
  const parking: RunQuestion = { kind: 'layout_input', fields: ['parking'] }
  expect(questionKey('r1', lot)).toBe(questionKey('r1', { ...lot }))
  expect(questionKey('r1', lot)).not.toBe(questionKey('r1', parking))
  expect(questionKey('r1', lot)).not.toBe(questionKey('r2', lot))
})

test('fields read in words with their inputs; the answer is typed and said back as the person line', () => {
  const question: RunQuestion = { kind: 'layout_input', fields: ['building_type', 'floor_area_m2', 'parking'],
    law_parking: { rule: '부설주차장 설치기준', article: '의정부시 주차장 조례 별표1', required_cars: null } }
  const fields = fieldsOf(question)
  expect(fields.map((field) => [field.label, field.input, field.unit ?? ''])).toEqual([['용도', 'select', ''], ['시설면적', 'number', '㎡'], ['주차 대수', 'integer', '대']])
  expect(fields[2]!.hint).toBe('법규 근거: 부설주차장 설치기준 · 의정부시 주차장 조례 별표1')
  expect(answerOf(fields, { building_type: '공장', floor_area_m2: '1000', parking: '' })).toEqual({ missing: '주차 대수' })
  expect(answerOf(fields, { building_type: '공장', floor_area_m2: '1000', parking: '2.5' })).toEqual({ missing: '주차 대수' })
  const answer = answerOf(fields, { building_type: '공장', floor_area_m2: '1000', parking: '12' })
  expect(answer).toEqual({ input: { building_type: '공장', floor_area_m2: 1000, parking: 12 } })
  expect(answerLine(fields, (answer as { input: Record<string, string | number> }).input)).toBe('용도: 공장 · 시설면적: 1000㎡ · 주차 대수: 12대')
  expect(fieldsOf({ kind: 'request_input', fields: ['something_new'] })[0]!.label).toBe('필요한 값')
})

test('an intent to reconfirm reads as its declared parts in words', () => {
  expect(intentLines({ kind: 'request_input', fields: ['confirm', 'context_hash', 'intent'],
    proposed_intent: { parti: '마당 중심', non_negotiables: ['남향 보육실', '안전한 동선'], unknown_key: 'x', precedents: '' } }))
    .toEqual(['파르티: 마당 중심', '양보할 수 없는 것: 남향 보육실, 안전한 동선'])
})


test('a refused answer reads as what the person can do, never in the owner wording', () => {
  expect(rejectionText('answer_rejected: run is not waiting for input')).toBe('이 질문은 이미 지나갔어요 — 실행이 다음 단계로 넘어갔어요.')
  expect(rejectionText('answer_rejected: district_lot must be one of the lots Law offered: A11')).toBe('후보로 나온 획지 중에서 골라 주세요.')
  expect(rejectionText('Owner unavailable')).toBe('답을 보내지 못했어요. 값을 확인하고 다시 보내 주세요.')
  expect(rejectionText(null)).toBe('답을 보내지 못했어요. 값을 확인하고 다시 보내 주세요.')
})
