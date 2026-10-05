import { expect, test } from 'bun:test'
import { parseSpecialistRequest, prepareReview } from './specialist-review'

const project = {
  project_id: 'native', owner_project_id: 'owner', branch_id: 'main',
  scene_id: 'scene', scene_revision: 1, scene_project_id: null,
}
const request = {
  goal: 'specialist_review',
  specialist_reviews: [{ agent: 'systems', tool: 'systems_analyze',
    args: { request: { schema_version: 'systems.hydraulic.request.v1', model_ref: 'owner-model' } },
    source_versions: { 'program.spaces': 3 } }],
}

test('Systems analytical owner request preserves exact payload and revision guard', () => {
  const parsed = parseSpecialistRequest(request, project)
  const attempt = prepareReview(parsed, { scene_revision: 1, source_versions: { 'program.spaces': 3 } }, project)
  expect(JSON.parse(attempt.body).request).toEqual(request)
  expect(() => prepareReview(parsed, { scene_revision: 1, source_versions: { 'program.spaces': 4 } }, project)).toThrow()
})

test('analytical route does not admit unknown authoring tools', () => {
  const invalid = structuredClone(request)
  invalid.specialist_reviews[0]!.tool = 'systems_publish'
  expect(() => parseSpecialistRequest(invalid, project)).toThrow()
})
