import { expect, test } from 'bun:test'

import { buildGraph, callOrder, GAP_X, NODE_WIDTH } from './graph'
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
  expect([hub.position.x, site.position.x, law.position.x, revision.position.x]).toEqual([0, NODE_WIDTH + GAP_X, 2 * (NODE_WIDTH + GAP_X), 3 * (NODE_WIDTH + GAP_X)])
  expect([site.position.y, law.position.y, revision.position.y]).toEqual([0, 0, 0])
  expect(mass.position.y).toBeGreaterThan(law.position.y + 84)
  expect(hub.sub).toBe('요청 3건 · 응답 2건')
  expect(law.sub).toBe('60/250')
  expect(mass.sub).toBe('')
  expect(edges.filter((edge) => edge.kind === 'next').map((edge) => [edge.source, edge.target, edge.label])).toEqual([
    ['site_context', 'law', '2번째'], ['law', 'revision', '3번째'],
  ])
  expect(edges.find((edge) => edge.kind === 'user')).toMatchObject({ source: 'user', target: 'orchestrator' })
  expect(edges.filter((edge) => edge.kind === 'request' || edge.kind === 'response').map((edge) => [edge.source, edge.target, edge.label, edge.said])).toEqual([
    ['orchestrator', 'site_context', '대지 사실 확인 요청 1건', ''], ['site_context', 'orchestrator', '응답 1건', '6/9'],
    ['orchestrator', 'law', '법규 한계 요청 1건', ''], ['law', 'orchestrator', '응답 1건 · 전송 미확인', '60/250'],
    ['orchestrator', 'revision', '재검토 판정 요청 1건', ''],
  ])
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
  expect(edges.find((edge) => edge.id === 'user→orchestrator')?.said).toBe('조경 의무 면적은 몇 퍼센트야?')
  expect(edges.find((edge) => edge.id === 'orchestrator→law')?.said).toBe('질문 건축법 제42조 조경 기준')
  expect(edges.find((edge) => edge.id === 'law→orchestrator')?.said).toBe('조문 1건: 건축법 제42조 (대지의 조경)')
  expect(edges.find((edge) => edge.id === 'orchestrator→user')?.said).toBe('조경은 건축법 제42조가 정해요.')
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
