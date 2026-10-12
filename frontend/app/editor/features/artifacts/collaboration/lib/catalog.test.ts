import { expect, test } from 'bun:test'

import type { AgentSummary } from '@/lib/orchestrator-runs/types'

import { humanize, liveOf, mergeCatalog, namesOf } from './catalog'

const row = (over: Partial<AgentSummary>): AgentSummary => ({ agent_id: 'x', label: 'x', capabilities: [], implementation_status: 'unknown', connection_status: 'not_declared', checked_at: null, evidence_ref: null, ...over })

test('names read like the rest of the network, whatever the catalog spells', () => {
  expect(humanize('construction')).toBe('Construction Agent')
  expect(humanize('DesignIntentAgent')).toBe('DesignIntent Agent')
  expect(humanize('site-context')).toBe('Site context Agent')
  expect([liveOf('available'), liveOf('local'), liveOf('unavailable'), liveOf('not_declared'), liveOf('http_provider_declared')]).toEqual(['up', 'up', 'down', null, null])
})

test('a known agent keeps its folder name and tools and takes its live state from the catalog; a hyphenated id resolves', () => {
  const entries = mergeCatalog([row({ agent_id: 'site-context', label: 'SiteContextAgent', capabilities: ['site_resolve', 'site_health'], connection_status: 'available' })])
  const site = entries.find((entry) => entry.id === 'site_context')!
  expect(site).toMatchObject({ label: 'Site Agent', live: 'up', known: true })
  expect(site.tools.site_resolve).toBe('대지 사실 확인')
  expect(entries.some((entry) => entry.id === 'orchestrator' || entry.id === 'user')).toBe(false)
})

test('an agent only the Orchestrator knows is drawn from the catalog: readable name, declared skills as what it answers, plumbing skills dropped', () => {
  const entries = mergeCatalog([row({ agent_id: 'structure', label: 'structure', capabilities: ['structure_frame', 'structure_health', 'structure_conversation_contract'], connection_status: 'local' })])
  const structure = entries.find((entry) => entry.id === 'structure')!
  expect(structure).toMatchObject({ label: 'Structure Agent', live: 'up', known: false, description: null })
  expect(structure.tools).toEqual({ structure_frame: 'frame' })
  expect(namesOf(entries).structure).toBe('Structure Agent')
  expect(entries.length).toBeGreaterThan(10)
})

test('with its A2A card the agent speaks for itself: description, skills by their card names, folder labels still first', () => {
  const entries = mergeCatalog([
    row({ agent_id: 'structure', label: 'StructureAgent', capabilities: ['structure_frame'], connection_status: 'available', description: 'Frames and walls for a mass.', skills: [{ id: 'structure_frame', name: 'frame', description: 'Propose a frame.' }, { id: 'structure_health', name: 'health', description: '' }] }),
    row({ agent_id: 'site-context', label: 'SiteContextAgent', capabilities: [], connection_status: 'available', description: 'Establishes the facts a parcel has.', skills: [{ id: 'site_resolve', name: 'resolve', description: '' }, { id: 'site_district_plan', name: 'district plan', description: '' }] }),
  ])
  expect(entries.find((entry) => entry.id === 'structure')).toMatchObject({ description: 'Frames and walls for a mass.', tools: { structure_frame: 'frame' } })
  const site = entries.find((entry) => entry.id === 'site_context')!
  expect(site.description).toBe('Establishes the facts a parcel has.')
  expect(site.tools).toEqual({ site_resolve: '대지 사실 확인', site_district_plan: 'district plan' })
})
