import { expect, test } from 'bun:test'
import { prepareFollowup, parseFollowupMaterial } from './followup-review'
const answers = { domain: '', proposal: '', sourceId: '', brief: '', operationalType: '', functionalType: '' }

test('domain conversation adds explicit proposals without upgrading source quality or inventing evidence', () => {
  const item = { agent: 'domain_expert', tool: 'domain_review', source_versions: { 'program.spaces': 3 },
    args: { request: { sources: [{ id: 'program', content: 'x'.repeat(12000), dirty: true, quality: 'needs_evidence' }], requirements: [], evidence: [] } } }
  const result = prepareFollowup(item, { ...answers, domain: 'office', proposal: 'Separate visitor and staff circulation' }, 'run1')
  const next = result.specialist_reviews[0]!.args.request as any
  expect(next.sources).toEqual(item.args.request.sources)
  expect(next.evidence).toEqual([])
  expect(next.requirements[0].provenance.professionally_verified).toBe(false)
  expect(next.requirements[0].source_id).toBeUndefined()
  expect(item.args.request.requirements).toEqual([])
})

test('Systems exploration asks the existing owner catalog without fabricating engineering inputs', () => {
  const next = prepareFollowup({ agent: 'systems', tool: 'systems_requirements', args: { request: { basis_ref: 'exact-owner-basis' } }, source_versions: { 'program.spaces': 3 } }, answers, 'r')
  expect(next.specialist_reviews[0]!.args.request).toEqual({ schema_version: 'systems.use.catalog.request.v1' })
  expect(next.specialist_reviews[0]!.source_versions).toEqual({ 'program.spaces': 3 })
})

test('follow-up original request refuses a foreign native binding even with matching owner', () => {
  expect(() => parseFollowupMaterial({}, { project_id: 'p', owner_project_id: 'owner', branch_id: 'main', scene_id: 's', scene_revision: 1, scene_project_id: null }, { run_id: 'r', request_id: 'editor:other:key' } as any)).toThrow()
})
