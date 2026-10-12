import { expect, test } from 'bun:test'

import { buildGraph, NODE_WIDTH } from './graph'
import type { CollaborationMessage } from './transcript'

const message = (over: Partial<CollaborationMessage>): CollaborationMessage => ({
  id: 'm', step: 1, direction: 'request', from: 'orchestrator', to: 'site_context', tool: 'site_resolve', state: 'succeeded', transport: 'a2a', truncated: false, text: '{}', ...over,
})

test('no records means no fabricated participants or edges', () => {
  expect(buildGraph([])).toEqual({ nodes: [], edges: [] })
})

test('only observed directions appear, named in the user\'s words, and an unknown transport stays marked', () => {
  const { nodes, edges } = buildGraph([
    message({ id: 'a' }),
    message({ id: 'b', direction: 'response', from: 'site_context', to: 'orchestrator', state: 'partial', transport: 'unknown', text: '{"summary":"6/9 site facts"}' }),
    message({ id: 'c', step: 3, to: 'law', tool: 'law_parcel_limits' }),
  ], 'law')
  expect(nodes.map((node) => [node.id, node.label, node.hub, node.selected])).toEqual([
    ['orchestrator', 'Orchestrator Agent', true, false], ['site_context', 'Site Agent', false, false], ['law', 'Law Agent', false, true],
  ])
  expect(nodes[0]!.position.x).toBe(0)
  expect(nodes[1]!.position.x).toBeGreaterThan(NODE_WIDTH)
  expect(nodes[1]!.sub).toBe('대지 사실 확인 · 근거 부족')
  expect(edges.map((edge) => [edge.source, edge.target, edge.label])).toEqual([
    ['orchestrator', 'site_context', '대지 사실 확인 요청 1건'], ['site_context', 'orchestrator', '응답 1건 · 전송 미확인'], ['orchestrator', 'law', '법규 한계 요청 1건'],
  ])
})
