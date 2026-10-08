import { expect, test } from 'bun:test'

import { neededAgents } from './activation'
import type { HostStatus } from '@/lib/orchestrator-runs/types'

const status = (states: Record<string, HostStatus['agents'][string]['state']>): HostStatus => ({
  at: 'x',
  daemon: { pid: 1, stale: false },
  agents: Object.fromEntries(Object.entries(states).map(([id, state]) => [id, { state, up: state === 'up', lease_until: null, idle_in_s: null }])),
})

test('neededAgents names the owners the host does not report up, in owner order, and ignores owners the host does not know', () => {
  const goal = { owners: ['program', 'masterplan', 'mass', 'revision'] }
  expect(neededAgents(goal, status({ program: 'absent', masterplan: 'up', mass: 'down', revision: 'up' }))).toEqual(['program', 'mass'])
  expect(neededAgents(goal, status({ program: 'up', masterplan: 'up', mass: 'up' }))).toEqual([])
  expect(neededAgents(goal, status({ mass: 'gave_up' }))).toEqual(['mass'])
  expect(neededAgents(goal, null)).toEqual([])
})
