import { expect, test } from 'bun:test'
import { renderToStaticMarkup } from 'react-dom/server'
import { ConversationArtifacts } from './ConversationArtifacts'

const artifact = { id: 'intent-review', owner: 'orchestrator', title: '검토', status: 'awaiting_confirmation', data: { kind: 'intent_reconfirmation', context_hash: 'a'.repeat(64), context: { nodes: { requirement: 4 } }, proposed_intent: { description: 'Review this intent' } } }

test('reviewable server confirmation has one action; ordinary proposals have none', () => {
  const html = renderToStaticMarkup(<ConversationArtifacts artifacts={[artifact]} onConfirm={() => {}} />)
  expect(html).toContain('변경된 조건으로 설계 의도 확인')
  expect(html).toContain('Review this intent')
  expect(html).toContain('requirement')
  const proposal = renderToStaticMarkup(<ConversationArtifacts artifacts={[{ ...artifact, status: 'proposal' }]} onConfirm={() => {}} />)
  expect(proposal).not.toContain('<button')
  const busy = renderToStaticMarkup(<ConversationArtifacts artifacts={[artifact]} disabled onConfirm={() => {}} />)
  expect(busy).toContain('disabled=""')
})

test('the requirement brief is one card in the user\'s words that fills in, never the owner\'s ids, codes or empty JSON', () => {
  const field = (name: string, data: Record<string, unknown>) => ({ id: `requirements.${name}.r1`, owner: 'requirement', title: `requirements.${name}`, status: 'needs_evidence', data })
  const html = renderToStaticMarkup(<ConversationArtifacts artifacts={[field('must_have', { value: [] }), field('raw_brief', { value: '어린이집을 지으려고 해요' }), field('unknowns', { value: ['대지면적'] }), artifact]} onConfirm={() => {}} />)
  expect(html).toContain('<strong>요구사항</strong>')
  expect(html).toContain('2/3 채워짐')
  expect(html.indexOf('원문 요청')).toBeLessThan(html.indexOf('꼭 필요한 것'))
  expect(html).toContain('어린이집을 지으려고 해요')
  expect(html).toContain('아직 없음')
  expect(html).not.toContain('requirements.')
  expect(html).not.toContain('근거 보완 필요')
  expect(html).not.toContain('<dt>value</dt>')
  // Other owners' artifacts keep their own cards after the sheet.
  expect(html.indexOf('요구사항')).toBeLessThan(html.indexOf('Review this intent'))
})

test('artifact status distinguishes proposals, stale evidence and confirmed results with a neutral fallback', () => {
  const cases = { proposed: '제안', stale: '이전 조건 기준', needs_evidence: '근거 보완 필요', confirmed: '확인됨', awaiting_confirmation: '확인 대기', valid: '현재 조건에 유효', future_status: '상태 미확인' }
  for (const [status, label] of Object.entries(cases)) {
    const html = renderToStaticMarkup(<ConversationArtifacts artifacts={[{ ...artifact, status }]} />)
    expect(html).toContain(`>${label}</span>`)
    expect(html).toContain('conversation-artifact-status')
    if (status === 'future_status') expect(html).toContain('data-tone="neutral"')
  }
})

test('confirmation foregrounds intent and hides context/hash inside collapsed review evidence', () => {
  const html = renderToStaticMarkup(<ConversationArtifacts artifacts={[artifact]} onConfirm={() => {}} />)
  expect(html).toContain('class="conversation-artifact" open=""')
  const evidenceAt = html.indexOf('<details class="conversation-review-evidence">')
  expect(evidenceAt).toBeGreaterThan(html.indexOf('Review this intent'))
  expect(html).toContain('<summary>검토 근거</summary>')
  expect(html.indexOf('context hash')).toBeGreaterThan(evidenceAt)
  expect(html.indexOf('a'.repeat(64))).toBeGreaterThan(evidenceAt)
  expect(html.indexOf('requirement')).toBeGreaterThan(evidenceAt)
  expect(html).not.toContain('intent_reconfirmation')
})
