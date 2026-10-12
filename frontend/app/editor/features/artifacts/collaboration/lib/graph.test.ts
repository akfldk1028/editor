import { expect, test } from 'bun:test'

import { buildGraph, CARD_WIDTH, callOrder, type GraphNode, NODE_WIDTH, SLOT } from './graph'
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

test('a wide canvas fans out from the Orchestrator: one row per agent in call order, the request card over the answer card, no line across another agent', () => {
  const { nodes, edges } = buildGraph(run, 'law', { catalog, live: { law: 'up', mass: 'down' } })
  expect(nodes.filter((node) => node.kind !== 'said').map((node) => [node.id, node.kind, node.order, node.idle, node.selected, node.live])).toEqual([
    ['user', 'user', null, false, false, null],
    ['orchestrator', 'hub', null, false, false, null],
    ['site_context', 'agent', 1, false, false, null],
    ['law', 'agent', 2, false, true, 'up'],
    ['revision', 'agent', 3, false, false, null],
    ['mass', 'agent', null, true, false, 'down'],
  ])
  const at = (id: string) => nodes.find((node) => node.id === id)!
  const [user, hub, site, law, revision, mass] = ['user', 'orchestrator', 'site_context', 'law', 'revision', 'mass'].map(at) as [GraphNode, GraphNode, GraphNode, GraphNode, GraphNode, GraphNode]
  expect(user.position.x).toBeLessThan(hub.position.x)
  // Every called agent stands in one column right of the Orchestrator, a row each, in the order it was called.
  expect(new Set([site, law, revision].map((node) => node.position.x)).size).toBe(1)
  expect(site.position.x).toBeGreaterThan(hub.position.x + NODE_WIDTH + CARD_WIDTH)
  expect(site.position.y).toBeLessThan(law.position.y)
  expect(law.position.y).toBeLessThan(revision.position.y)
  // Each row's request card sits over its answer card, between the Orchestrator and the agent.
  const request = at('said:orchestrator→law')
  const answer = at('said:law→orchestrator')
  expect(request.position.x).toBe(answer.position.x)
  expect(answer.position.y).toBe(request.position.y + SLOT)
  expect(request.position.x).toBeGreaterThan(hub.position.x + NODE_WIDTH)
  expect(request.position.x + CARD_WIDTH).toBeLessThan(law.position.x)
  expect(mass.position.y).toBeGreaterThan(revision.position.y + 84)
  expect(hub.sub).toBe('요청 3건 · 응답 2건')
  expect(law.sub).toBe('60/250')
  expect(mass.sub).toBe('')
  // No 'next' lines: the numbers on the cards carry the order.
  expect(edges.some((edge) => edge.kind === 'next')).toBe(false)
  expect(edges.find((edge) => edge.kind === 'user')).toMatchObject({ source: 'user', target: 'orchestrator', sourceHandle: 'out', targetHandle: 'in' })
  expect(edges.filter((edge) => edge.id.startsWith('orchestrator→law') || edge.id.startsWith('law→orchestrator')).map((edge) => [edge.source, edge.sourceHandle, edge.target, edge.targetHandle])).toEqual([
    ['orchestrator', 'out', 'said:orchestrator→law', 't-left'], ['said:orchestrator→law', 's-right', 'law', 'in'],
    ['law', 'back', 'said:law→orchestrator', 't-right'], ['said:law→orchestrator', 's-left', 'orchestrator', 'return'],
  ])
  expect(at('said:law→orchestrator').said).toMatchObject({ text: '60/250', known: false })
  expect(at('said:orchestrator→revision').said?.caption).toBe('Orchestrator Agent → Revision Agent · 재검토 판정 요청')
})

test('what was said is on the canvas: the person’s question on their card and on the line to the Orchestrator, the answer on the line back', () => {
  const talk = [
    message({ id: 'q', from: 'user', to: 'orchestrator', tool: 'ask', text: '조경 의무 면적은 몇 퍼센트야?' }),
    message({ id: 'r', to: 'law', tool: 'law_search', text: '{"query": "건축법 제42조 조경 기준", "limit": 8}' }),
    message({ id: 's', direction: 'response', from: 'law', to: 'orchestrator', tool: 'law_search', text: '{"results": [{"law": "건축법", "article": "제42조", "title": "대지의 조경"}], "total": 1}' }),
    message({ id: 't', direction: 'response', from: 'orchestrator', to: 'user', tool: '', text: '조경은 건축법 제42조가 정해요.' }),
  ]
  const { nodes, edges } = buildGraph(talk, null, { catalog: [{ id: 'law' }] })
  expect(nodes.find((node) => node.id === 'user')?.sub).toBe('조경 의무 면적은 몇 퍼센트야?')
  expect(nodes.find((node) => node.id === 'orchestrator')?.sub).toBe('조경은 건축법 제42조가 정해요.')
  const said = (id: string) => nodes.find((node) => node.id === `said:${id}`)?.said?.text
  expect(said('user→orchestrator')).toBe('조경 의무 면적은 몇 퍼센트야?')
  expect(said('orchestrator→law')).toBe('질문 건축법 제42조 조경 기준')
  expect(said('law→orchestrator')).toBe('조문 1건: 건축법 제42조 (대지의 조경)')
  expect(said('orchestrator→user')).toBe('조경은 건축법 제42조가 정해요.')
  // The person's question sits above the reply, both between the person and the Orchestrator.
  expect(nodes.find((node) => node.id === 'said:user→orchestrator')!.position.y).toBeLessThan(nodes.find((node) => node.id === 'said:orchestrator→user')!.position.y)
  expect(edges.some((edge) => edge.id.startsWith('orchestrator→user') && edge.source === 'orchestrator' && edge.sourceHandle === 'back')).toBe(true)
})

test('a narrow canvas stacks the flow: person, their words, Orchestrator, each call’s card, the agent, its answer; requests go down the left lane, answers return on the right', () => {
  const talk = [
    message({ id: 'q', from: 'user', to: 'orchestrator', tool: 'ask', text: '조경 의무 면적은 몇 퍼센트야?' }),
    message({ id: 'r', to: 'law', tool: 'law_search', text: '{"query": "조경"}' }),
    message({ id: 's', direction: 'response', from: 'law', to: 'orchestrator', tool: 'law_search', text: '{"summary": "조문 1건"}' }),
    message({ id: 't', direction: 'response', from: 'orchestrator', to: 'user', tool: '', text: '건축법 제42조가 정해요.' }),
  ]
  const { nodes, edges } = buildGraph(talk, null, { catalog: [{ id: 'law' }, { id: 'mass' }, { id: 'site_context' }], orientation: 'vertical' })
  const column = nodes.filter((node) => !node.idle)
  expect(column.map((node) => [node.id, node.kind])).toEqual([
    ['user', 'user'], ['said:user→orchestrator', 'said'], ['orchestrator', 'hub'], ['said:orchestrator→law', 'said'], ['law', 'agent'], ['said:law→orchestrator', 'said'], ['said:orchestrator→user', 'said'],
  ])
  for (let index = 1; index < column.length; index++) expect(column[index]!.position.y).toBeGreaterThan(column[index - 1]!.position.y)
  expect(column[1]!.said).toEqual({ text: '조경 의무 면적은 몇 퍼센트야?', full: '조경 의무 면적은 몇 퍼센트야?', caption: '사용자 → Orchestrator Agent · 질문', kind: 'request', running: false, known: true })
  expect(column[3]!.said?.caption).toBe('Orchestrator Agent → Law Agent · 법령 검색 요청')
  expect(column[5]!.said?.caption).toBe('Law Agent의 답')
  expect(column[5]!.said?.text).toBe('조문 1건')
  expect(edges.map((edge) => [edge.source, edge.target, edge.lane])).toEqual([
    ['user', 'said:user→orchestrator', 'down'], ['said:user→orchestrator', 'orchestrator', 'down'],
    ['orchestrator', 'said:orchestrator→law', 'left'], ['said:orchestrator→law', 'law', 'down'],
    ['law', 'said:law→orchestrator', 'down'], ['said:law→orchestrator', 'orchestrator', 'right'],
    ['orchestrator', 'said:orchestrator→user', 'right'], ['said:orchestrator→user', 'user', 'left'],
  ])
  const idle = nodes.filter((node) => node.idle)
  expect(idle.map((node) => node.id)).toEqual(['mass', 'site_context'])
  expect(idle[0]!.position.y).toBeGreaterThan(column[6]!.position.y)
  expect(idle[0]!.position.y).toBe(idle[1]!.position.y)
})

test('an owner that answered the person directly gets its own card in the column, back to the person', () => {
  const talk = [
    message({ id: 'q', from: 'user', to: 'orchestrator', tool: 'conversation', text: '용적률 상한은?' }),
    message({ id: 'a', direction: 'response', from: 'law', to: 'user', tool: '', text: '용적률 상한은 250퍼센트입니다.' }),
  ]
  const { nodes, edges } = buildGraph(talk, null, { catalog: [{ id: 'law' }], orientation: 'vertical' })
  expect(nodes.filter((node) => !node.idle).map((node) => node.id)).toEqual(['user', 'said:user→orchestrator', 'orchestrator', 'said:orchestrator→law', 'law', 'said:law→user'])
  expect(nodes.find((node) => node.id === 'said:law→user')?.said).toMatchObject({ text: '용적률 상한은 250퍼센트입니다.', full: '용적률 상한은 250퍼센트입니다.', caption: 'Law Agent의 답', known: true })
  // The relay the Orchestrator made but did not record: drawn, marked unknown, nothing invented about what was asked.
  expect(nodes.find((node) => node.id === 'said:orchestrator→law')?.said).toMatchObject({ caption: 'Orchestrator Agent → Law Agent · 전달', known: false })
  expect(edges.filter((edge) => edge.id.startsWith('law→user')).map((edge) => [edge.source, edge.target, edge.lane])).toEqual([['law', 'said:law→user', 'down'], ['said:law→user', 'user', 'left']])
})

test('without a catalog every agent the conversation knows is on the canvas, in rows that do not overlap', () => {
  const { nodes } = buildGraph([])
  const waiting = nodes.filter((node) => node.idle)
  expect(waiting.length).toBeGreaterThan(10)
  const rows = new Set(waiting.map((node) => node.position.y))
  expect(rows.size).toBeGreaterThan(1)
  for (const node of waiting) for (const other of waiting) if (node !== other && node.position.y === other.position.y) expect(Math.abs(node.position.x - other.position.x)).toBeGreaterThanOrEqual(NODE_WIDTH)
})
