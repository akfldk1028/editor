import { expect, test } from 'bun:test'

import { buildGraph, callOrder, NODE_WIDTH } from './graph'
import type { CollaborationMessage } from './transcript'

const message = (over: Partial<CollaborationMessage>): CollaborationMessage => ({
  id: 'm', step: 1, direction: 'request', from: 'orchestrator', to: 'site_context', tool: 'site_resolve', state: 'succeeded', transport: 'a2a', truncated: false, text: '{}', ...over,
})
const catalog = [{ id: 'site_context', tools: { site_resolve: '대지 사실 확인' } }, { id: 'law', tools: { law_parcel_limits: '법규 한계' } }, { id: 'mass', tools: {} }, { id: 'revision', tools: { revision_triage: '재검토 판정' } }]
const run = [
  message({ id: 'a' }),
  message({ id: 'b', direction: 'response', from: 'site_context', to: 'orchestrator', state: 'partial', text: '{"summary":"6/9"}' }),
  message({ id: 'c', step: 3, to: 'law', tool: 'law_parcel_limits' }),
  message({ id: 'd', step: 4, direction: 'response', from: 'law', to: 'orchestrator', tool: 'law_parcel_limits', state: 'succeeded', transport: 'unknown', text: '{"summary":"60/250"}' }),
  message({ id: 'e', step: 5, to: 'revision', tool: 'revision_triage' }),
]

test('an empty catalog with no records draws nothing; the call order is the order the Orchestrator first spoke to each agent', () => {
  expect(buildGraph([], null, { catalog: [] })).toEqual({ nodes: [], edges: [] })
  expect(callOrder(run)).toEqual(['site_context', 'law', 'revision'])
})

test('the flow reads left to right as it ran: person → Orchestrator → Site → Law → Revision, numbered; the uncalled agent waits below, dimmed', () => {
  const { nodes, edges } = buildGraph(run, 'law', { catalog, live: { law: 'up', mass: 'down' } })
  expect(nodes.map((node) => [node.id, node.kind, node.order, node.idle, node.selected, node.live])).toEqual([
    ['user', 'user', null, false, false, null],
    ['orchestrator', 'hub', null, false, false, null],
    ['site_context', 'agent', 1, false, false, null],
    ['law', 'agent', 2, false, true, 'up'],
    ['revision', 'agent', 3, false, false, null],
    ['mass', 'agent', null, true, false, 'down'],
  ])
  const [user, hub, site, law, revision, mass] = nodes as [typeof nodes[number], typeof nodes[number], typeof nodes[number], typeof nodes[number], typeof nodes[number], typeof nodes[number]]
  expect(user.position.x).toBeLessThan(hub.position.x)
  expect([hub.position.x, site.position.x, law.position.x, revision.position.x]).toEqual([0, NODE_WIDTH + 120, 2 * (NODE_WIDTH + 120), 3 * (NODE_WIDTH + 120)])
  expect([site.position.y, law.position.y, revision.position.y]).toEqual([0, 0, 0])
  expect(mass.position.y).toBeGreaterThan(law.position.y + 84)
  expect(hub.sub).toBe('요청 3건 · 응답 2건')
  expect(law.sub).toBe('법규 한계 · 성공')
  expect(mass.sub).toBe('')
  expect(edges.filter((edge) => edge.kind === 'next').map((edge) => [edge.source, edge.target, edge.label])).toEqual([
    ['site_context', 'law', '2번째'], ['law', 'revision', '3번째'],
  ])
  expect(edges.find((edge) => edge.kind === 'user')).toMatchObject({ source: 'user', target: 'orchestrator' })
  expect(edges.filter((edge) => edge.kind === 'request' || edge.kind === 'response').map((edge) => [edge.source, edge.target, edge.label])).toEqual([
    ['orchestrator', 'site_context', '대지 사실 확인 요청 1건'], ['site_context', 'orchestrator', '응답 1건'],
    ['orchestrator', 'law', '법규 한계 요청 1건'], ['law', 'orchestrator', '응답 1건 · 전송 미확인'],
    ['orchestrator', 'revision', '재검토 판정 요청 1건'],
  ])
})

test('without a catalog every agent the conversation knows is on the canvas, in rows that do not overlap', () => {
  const { nodes } = buildGraph([])
  const waiting = nodes.filter((node) => node.idle)
  expect(waiting.length).toBeGreaterThan(10)
  const rows = new Set(waiting.map((node) => node.position.y))
  expect(rows.size).toBeGreaterThan(1)
  for (const node of waiting) for (const other of waiting) if (node !== other && node.position.y === other.position.y) expect(Math.abs(node.position.x - other.position.x)).toBeGreaterThanOrEqual(NODE_WIDTH)
})
