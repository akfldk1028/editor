import { expect, test } from 'bun:test'

import type { Workflow } from '@/lib/design-conversation/workflow'

import { PATTERN_COLUMN, patternLinks, patternNodes, patternOf } from './pattern'
import type { CollaborationMessage } from './transcript'

const message = (over: Partial<CollaborationMessage>): CollaborationMessage => ({
  id: 'm', step: 1, direction: 'request', from: 'orchestrator', to: 'site_context', tool: 'site_resolve', state: 'succeeded', transport: 'a2a', truncated: false, text: '{}', ...over,
})
const timed = (id: string, direction: 'request' | 'response', to: string, tool: string, at: number, state = 'succeeded'): CollaborationMessage =>
  message({ id: `hop:${id}:${direction}`, direction, from: direction === 'request' ? 'orchestrator' : to, to: direction === 'request' ? to : 'orchestrator', tool, at, state })

test('without a declared workflow the pattern is the calls as timed: one column per wave, every earlier call leading to each later one', () => {
  const turn = [
    timed('1', 'request', 'site_context', 'site_surroundings', 2000), timed('1', 'response', 'site_context', 'site_surroundings', 3300),
    timed('2', 'request', 'site_context', 'site_zoning', 2100), timed('2', 'response', 'site_context', 'site_zoning', 4600),
    timed('3', 'request', 'law', 'law_land_analyze', 5000, 'running'),
  ]
  const pattern = patternOf(turn, null, 9000)
  expect(pattern.declared).toBe(false)
  expect(pattern.steps).toEqual([
    { id: 'call:0:0', owner: 'site_context', title: '주변 현황', status: 'succeeded', column: 0 },
    { id: 'call:0:1', owner: 'site_context', title: '용도지역', status: 'succeeded', column: 0 },
    { id: 'call:1:0', owner: 'law', title: '법규 분석', status: 'running', column: 1 },
  ])
  expect(pattern.edges).toEqual([{ source: 'call:0:0', target: 'call:1:0' }, { source: 'call:0:1', target: 'call:1:0' }])
  const nodes = patternNodes(pattern, { law: 'Law Agent' })
  expect(nodes.map((node) => [node.id, node.agent, node.label, node.sub, node.order, node.position.x])).toEqual([
    ['user', 'user', '사용자', '요청', null, 0],
    ['orchestrator', 'orchestrator', 'Orchestrator Agent', '순서를 정함', null, PATTERN_COLUMN],
    ['call:0:0', 'site_context', 'Site Agent', '주변 현황 · 완료', 1, PATTERN_COLUMN * 2],
    ['call:0:1', 'site_context', 'Site Agent', '용도지역 · 완료', 1, PATTERN_COLUMN * 2],
    ['call:1:0', 'law', 'Law Agent', '법규 분석 · 진행 중', 2, PATTERN_COLUMN * 3],
  ])
  // Same-time calls share a column, one above the other, centred on the row.
  expect(nodes[2]!.position.y).toBe(-nodes[3]!.position.y)
  expect(patternLinks(pattern).map((link) => [link.id, link.running])).toEqual([
    ['user>hub', false], ['hub>call:0:0', false], ['hub>call:0:1', false], ['call:0:0>call:1:0', true], ['call:0:1>call:1:0', true],
  ])
})

test('a declared workflow is drawn by its own steps and dependencies; an evidence-only reading counts as done', () => {
  const workflow: Workflow = {
    id: 'workflow.x', protocol: 'sequential', status: 'running', revision: 2,
    steps: {
      a: { owner: 'site_context', tool: 'site_zoning', phase: 'propose', status: 'succeeded', title: '용도지역 확인' },
      b: { owner: 'law', tool: 'law_ordinance', phase: 'review', status: 'needs_evidence', code: 'law_evidence_only' },
      c: { owner: 'law', tool: 'law_parcel_limits', phase: 'verify', status: 'running' },
    },
    edges: [{ source: 'a', target: 'b' }, { source: 'b', target: 'c' }],
  }
  const pattern = patternOf([], workflow)
  expect(pattern.declared).toBe(true)
  expect(pattern.steps.map((step) => [step.id, step.column, step.title])).toEqual([['a', 0, '용도지역 확인'], ['b', 1, 'ordinance'], ['c', 2, 'parcel limits']])
  expect(patternNodes(pattern).map((node) => node.sub)).toEqual(['요청', '함께 작업을 계획함', '용도지역 확인 · 완료', 'ordinance · 원문 확인', 'parcel limits · 진행 중'])
  expect(patternLinks(pattern).map((link) => [link.id, link.done, link.running])).toEqual([
    ['user>hub', true, false], ['hub>a', true, false], ['a>b', true, false], ['b>c', false, true],
  ])
  expect(patternOf([], null)).toEqual({ steps: [], edges: [], declared: false })
})
