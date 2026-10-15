import { expect, test } from 'bun:test'

import { splitArtifacts } from './artifact-view'
import type { ConversationArtifact } from './types'

const workflow = (id: string, run: string, status: string): ConversationArtifact => ({
  id: `workflow.${id}`, owner: 'orchestrator', title: 'parallel', status,
  data: { protocol: 'parallel', status, run_id: run, steps: { a: { owner: 'law', tool: 'law_article', phase: 'lookup', status: status === 'running' ? 'running' : 'succeeded' } }, edges: [] },
})
const proposal = (id: string, owner: string, status: string): ConversationArtifact => ({ id: `proposal.${id}`, owner, title: id, status, data: { note: id } })

test('the conversation shows the latest turn and what waits for the person; earlier records are the past', () => {
  const artifacts = [
    workflow('w1', 'run-1', 'completed'), proposal('p1', 'orchestrator', 'proposed'), workflow('w2', 'run-2', 'blocked'),
    proposal('p2', 'masterplan', 'proposed'), workflow('w3', 'run-3', 'blocked'), workflow('w4', 'run-3', 'needs_evidence'),
    { ...proposal('c1', 'design_intent', 'awaiting_confirmation'), id: 'confirmation.c1' }, proposal('p3', 'design_intent', 'stale'),
  ]
  const { live, past } = splitArtifacts(artifacts)
  expect(live.map((a) => a.id)).toEqual(['proposal.p2', 'workflow.w3', 'workflow.w4', 'confirmation.c1'])
  expect(past.map((a) => a.id)).toEqual(['workflow.w1', 'proposal.p1', 'workflow.w2', 'proposal.p3'])
  // A workflow still running from an earlier turn stays in front.
  const running = splitArtifacts([workflow('old', 'run-0', 'running'), workflow('new', 'run-9', 'completed')])
  expect(running.live.map((a) => a.id)).toEqual(['workflow.old', 'workflow.new'])
  expect(splitArtifacts([])).toEqual({ live: [], past: [] })
})
