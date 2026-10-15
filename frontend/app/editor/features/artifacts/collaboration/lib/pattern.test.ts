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
  expect(pattern.steps.map(({ messages, ...step }) => [step, messages.map((message) => message.id)])).toEqual([
    [{ id: 'call:0:0', owner: 'site_context', title: '주변 현황', status: 'succeeded', column: 0 }, ['hop:1:request', 'hop:1:response']],
    [{ id: 'call:0:1', owner: 'site_context', title: '용도지역', status: 'succeeded', column: 0 }, ['hop:2:request', 'hop:2:response']],
    [{ id: 'call:1:0', owner: 'law', title: '법규 분석', status: 'running', column: 1 }, ['hop:3:request']],
  ])
  expect(pattern.edges).toEqual([{ source: 'call:0:0', target: 'call:1:0' }, { source: 'call:0:1', target: 'call:1:0' }])
  const nodes = patternNodes(pattern, { law: 'Law Agent' }, [], turn)
  expect(nodes.map((node) => [node.id, node.agent, node.label, node.sub, node.status, node.order, node.position.x])).toEqual([
    ['user', 'user', '사용자', '요청을 내고 답을 받습니다', undefined, null, 0],
    ['orchestrator', 'orchestrator', 'Orchestrator Agent', '', undefined, null, PATTERN_COLUMN],
    ['call:0:0', 'site_context', 'Site Agent', '주변 현황', '완료', 1, PATTERN_COLUMN * 2],
    ['call:0:1', 'site_context', 'Site Agent', '용도지역', '완료', 1, PATTERN_COLUMN * 2],
    ['call:1:0', 'law', 'Law Agent', '법규 분석', '진행 중', 2, PATTERN_COLUMN * 3],
  ])
  // A step's card steps through what it exchanged: the request, then the answer, as the 에이전트 view's cards do.
  expect(nodes[2]!.items.map((item) => item.id)).toEqual(['hop:1:request', 'hop:1:response'])
  expect(nodes[4]!.items.map((item) => item.id)).toEqual(['hop:3:request'])
  // Same-time calls share a column, one above the other, centred on the row.
  expect(nodes[2]!.position.y).toBe(-nodes[3]!.position.y)
  // The same edge records the 에이전트 view draws: the person's line, request lines from the hub, dotted order lines.
  expect(patternLinks(pattern).map((link) => [link.id, link.kind, link.label, !!link.running])).toEqual([
    ['person:user→orchestrator', 'user', '', false],
    ['orchestrator→call:0:0', 'request', '주변 현황 요청', false], ['orchestrator→call:0:1', 'request', '용도지역 요청', false],
    ['next:call:0:0→call:1:0', 'next', '다음', true], ['next:call:0:1→call:1:0', 'next', '다음', true],
  ])
  // The person and the Orchestrator keep the cards the 에이전트 view gave them (what they said), moved into place.
  const said = { id: 'orchestrator', label: 'Orchestrator Agent', sub: '순서를 정했어요', kind: 'hub' as const, items: [], order: null, selected: false, idle: false, live: null, position: { x: 500, y: 9 } }
  const reused = patternNodes(pattern, {}, [said])
  expect(reused[1]).toMatchObject({ id: 'orchestrator', agent: 'orchestrator', sub: '순서를 정했어요', position: { x: PATTERN_COLUMN, y: 0 } })
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
  // The record of the turn: the workflow's steps are matched to the calls to their owner for their tool, in order.
  const record = [
    timed('1', 'request', 'site_context', 'site_zoning', 1000), timed('1', 'response', 'site_context', 'site_zoning', 1500),
    timed('2', 'request', 'law', 'law_ordinance', 2000, 'needs_evidence'), timed('2', 'response', 'law', 'law_ordinance', 2300, 'needs_evidence'),
    timed('3', 'request', 'law', 'law_parcel_limits', 3000, 'running'),
  ]
  const pattern = patternOf(record, workflow)
  expect(pattern.declared).toBe(true)
  expect(pattern.steps.map((step) => [step.id, step.column, step.title, step.messages.map((message) => message.id)])).toEqual([
    ['a', 0, '용도지역 확인', ['hop:1:request', 'hop:1:response']], ['b', 1, 'ordinance', ['hop:2:request', 'hop:2:response']], ['c', 2, 'parcel limits', ['hop:3:request']]])
  const nodes = patternNodes(pattern, {}, [], record)
  expect(nodes.map((node) => [node.sub, node.status])).toEqual([['요청을 내고 답을 받습니다', undefined], ['', undefined], ['용도지역 확인', '완료'], ['ordinance', '원문 확인'], ['parcel limits', '진행 중']])
  expect(nodes[3]!.items.map((item) => item.id)).toEqual(['hop:2:request', 'hop:2:response'])
  expect(patternLinks(pattern).map((link) => [link.id, link.kind, link.label, !!link.running])).toEqual([
    ['person:user→orchestrator', 'user', '', false], ['orchestrator→a', 'request', '용도지역 확인 요청', false], ['next:a→b', 'next', '검토', false], ['next:b→c', 'next', '검증', true],
  ])
  expect(patternOf([], null)).toEqual({ steps: [], edges: [], declared: false })
})
