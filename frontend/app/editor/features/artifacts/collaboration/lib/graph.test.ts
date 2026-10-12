import { expect, test } from 'bun:test'

import { buildGraph, NODE_WIDTH } from './graph'
import type { CollaborationMessage } from './transcript'

const message = (over: Partial<CollaborationMessage>): CollaborationMessage => ({
  id: 'm', step: 1, direction: 'request', from: 'orchestrator', to: 'site_context', tool: 'site_resolve', state: 'succeeded', transport: 'a2a', truncated: false, text: '{}', ...over,
})
const catalog = [{ id: 'site_context', tools: { site_resolve: '대지 사실 확인' } }, { id: 'law', tools: { law_parcel_limits: '법규 한계' } }, { id: 'mass', tools: {} }]

test('an empty catalog and no records means nothing is drawn', () => {
  expect(buildGraph([], null, { catalog: [] })).toEqual({ nodes: [], edges: [] })
})

test('the whole network is drawn: the ones this run spoke with first and bright, the rest dimmed with what they answer', () => {
  const { nodes, edges } = buildGraph([
    message({ id: 'a', to: 'law', tool: 'law_parcel_limits' }),
    message({ id: 'b', direction: 'response', from: 'law', to: 'orchestrator', tool: 'law_parcel_limits', state: 'succeeded', transport: 'unknown', text: '{"summary":"60/250"}' }),
  ], 'law', { catalog, live: { law: 'up', mass: 'down' } })
  expect(nodes.map((node) => [node.id, node.label, node.idle, node.selected, node.live])).toEqual([
    ['orchestrator', 'Orchestrator Agent', false, false, null],
    ['law', 'Law Agent', false, true, 'up'],
    ['site_context', 'Site Agent', true, false, null],
    ['mass', 'Mass Agent', true, false, 'down'],
  ])
  expect(nodes[0]!.position.x).toBe(0)
  expect(nodes[0]!.sub).toBe('요청 1건 · 응답 1건')
  expect(nodes[1]!.position.x).toBeGreaterThan(NODE_WIDTH)
  expect(nodes[1]!.sub).toBe('법규 한계 · 성공')
  expect(nodes[2]!.sub).toBe('대지 사실 확인')
  expect(edges.map((edge) => [edge.source, edge.target, edge.label])).toEqual([
    ['orchestrator', 'law', '법규 한계 요청 1건'], ['law', 'orchestrator', '응답 1건 · 전송 미확인'],
  ])
})

test('without a catalog every agent the conversation knows is on the canvas', () => {
  const { nodes } = buildGraph([])
  expect(nodes.length).toBeGreaterThan(10)
  expect(nodes.some((node) => node.id === 'user')).toBe(false)
  expect(nodes.every((node) => node.hub || node.idle)).toBe(true)
})
