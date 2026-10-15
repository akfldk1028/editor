import { expect, test } from 'bun:test'

import { chatArtifacts } from './artifact-view'
import type { ConversationArtifact } from './types'

const workflow = (id: string, status: string): ConversationArtifact => ({
  id: `workflow.${id}`, owner: 'orchestrator', title: 'parallel', status,
  data: { protocol: 'parallel', status, run_id: id, steps: { a: { owner: 'law', tool: 'law_article', phase: 'lookup', status: 'succeeded' } }, edges: [] },
})
const proposal = (id: string, owner: string, status: string): ConversationArtifact => ({ id: `proposal.${id}`, owner, title: id, status, data: { note: id } })

test('the chat shows only what the person acts on and the newest proposal; workflow records and old cards stay out', () => {
  const artifacts = [
    workflow('w1', 'completed'), proposal('p1', 'orchestrator', 'proposed'), workflow('w2', 'running'),
    proposal('p2', 'masterplan', 'proposed'), { ...proposal('c1', 'design_intent', 'awaiting_confirmation'), id: 'confirmation.c1' },
    proposal('p3', 'design_intent', 'stale'), { ...proposal('c0', 'design_intent', 'confirmed'), id: 'confirmation.c0' },
  ]
  expect(chatArtifacts(artifacts).map((a) => a.id)).toEqual(['proposal.p2', 'confirmation.c1'])
  expect(chatArtifacts([workflow('w', 'running')])).toEqual([])
})
