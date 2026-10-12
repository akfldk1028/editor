import { expect, test } from 'bun:test'
import { requirementsSheet } from './sheet'

const field = (name: string, data: Record<string, unknown>, status = 'needs_evidence') => ({ id: `requirements.${name}.r1`, owner: 'requirement', title: `requirements.${name}`, status, data })

test('the owner\'s per-field artifacts become one sheet in display order, empty fields unfilled, wrappers removed', () => {
  const { sheet, rest } = requirementsSheet([
    field('assumptions', {}), field('must_have', { value: [] }), field('unknowns', { value: ['대지면적', '예산'] }),
    field('raw_brief', { value: '어린이집을 지으려고 해요' }),
    field('structured_brief', { building_type: '어린이집', pnu: '산곡동 684-1' }, 'stale'),
    { id: 'intent-review', owner: 'orchestrator', title: '검토', status: 'awaiting_confirmation', data: { kind: 'intent_reconfirmation' } },
  ])
  expect(rest.map((artifact) => artifact.id)).toEqual(['intent-review'])
  expect(sheet?.fields.map((item) => [item.key, item.label, item.filled])).toEqual([
    ['raw_brief', '원문 요청', true], ['structured_brief', '정리된 조건', true], ['must_have', '꼭 필요한 것', false],
    ['assumptions', '가정', false], ['unknowns', '아직 확인할 것', true],
  ])
  expect(sheet?.fields[0]?.value).toBe('어린이집을 지으려고 해요')
  // The structured brief's keys read in the user's words.
  expect(sheet?.fields[1]?.value).toEqual({ 용도: '어린이집', 지번: '산곡동 684-1' })
  expect(sheet?.filled).toBe(3)
  expect(sheet?.total).toBe(5)
  expect(sheet?.stale).toBe(true)
})

test('no requirement artifacts means no sheet; a field the owner adds later keeps its own key', () => {
  expect(requirementsSheet([]).sheet).toBeNull()
  const { sheet } = requirementsSheet([field('site_notes', { value: '남향' })])
  expect(sheet?.fields).toEqual([{ key: 'site_notes', label: 'site notes', value: '남향', filled: true }])
  expect(sheet?.stale).toBe(false)
})
