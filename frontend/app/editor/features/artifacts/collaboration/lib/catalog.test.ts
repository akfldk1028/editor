import { expect, test } from 'bun:test'

import type { AgentSummary } from '@/lib/orchestrator-runs/types'

import { humanize, liveOf, mergeCatalog, namesOf } from './catalog'

const row = (over: Partial<AgentSummary>): AgentSummary => ({ agent_id: 'x', label: 'x', capabilities: [], implementation_status: 'unknown', connection_status: 'not_declared', checked_at: null, evidence_ref: null, ...over })

test('names read like the rest of the network, whatever the catalog spells', () => {
  expect(humanize('construction')).toBe('Construction Agent')
  expect(humanize('DesignIntentAgent')).toBe('DesignIntent Agent')
  expect(humanize('site-context')).toBe('Site context Agent')
  expect([liveOf('available'), liveOf('not_declared'), liveOf('unreachable')]).toEqual(['up', null, 'down'])
})

test('a known agent keeps its folder name and tools and takes its live state from the catalog; a hyphenated id resolves', () => {
  const entries = mergeCatalog([row({ agent_id: 'site-context', label: 'SiteContextAgent', capabilities: ['site_resolve', 'site_health'], connection_status: 'available' })])
  const site = entries.find((entry) => entry.id === 'site_context')!
  expect(site).toMatchObject({ label: 'Site Agent', live: 'up', known: true })
  expect(site.tools.site_resolve).toBe('대지 사실 확인')
  expect(entries.some((entry) => entry.id === 'orchestrator' || entry.id === 'user')).toBe(false)
})

test('an agent only the Orchestrator knows is drawn from the catalog: readable name, declared skills as what it answers, plumbing skills dropped', () => {
  const entries = mergeCatalog([row({ agent_id: 'structure', label: 'structure', capabilities: ['structure_frame', 'structure_health', 'structure_conversation_contract'], connection_status: 'available' })])
  const structure = entries.find((entry) => entry.id === 'structure')!
  expect(structure).toMatchObject({ label: 'Structure Agent', live: 'up', known: false })
  expect(structure.tools).toEqual({ structure_frame: 'frame' })
  expect(namesOf(entries).structure).toBe('Structure Agent')
  expect(entries.length).toBeGreaterThan(10)
})
