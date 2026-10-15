import { expect, test } from 'bun:test'
import { phaseLabel, protocolLabel, stepOrder, stepStatus, stepTitle, workflowLayout, workflowOf, workflowStatus } from './workflow'

const artifact = (steps: Record<string, unknown>, edges: unknown[] = []) => ({
  id: 'workflow.test', owner: 'orchestrator', title: 'mesh', status: 'running',
  data: { protocol: 'mesh', status: 'running', steps, edges, revision: 1, selection: { mode: 'auto' } },
})
const step = (owner = 'program', status = 'pending') => ({ owner, tool: 'read', phase: 'propose', status })

test('repeated calls to one owner remain distinct steps and preserve exact dependency edges', () => {
  const flow = workflowOf(artifact({ proposal: step(), review: step('law'), revise: step() }, [
    { source: 'proposal', target: 'review' }, { source: 'review', target: 'revise' },
  ]))!
  const graph = workflowLayout(flow)
  expect(graph.nodes.map(n => n.id)).toEqual(['proposal', 'review', 'revise'])
  expect(graph.nodes[0]!.position.y).toBeLessThan(graph.nodes[1]!.position.y)
  expect(graph.nodes[1]!.position.y).toBeLessThan(graph.nodes[2]!.position.y)
  expect(graph.edges.map(e => [e.source, e.target])).toEqual([['proposal', 'review'], ['review', 'revise']])
})

test('independent steps share a rank; status refresh keeps identities and layout', () => {
  const input = artifact({ a: step(), b: step('law') })
  const before = workflowLayout(workflowOf(input)!)
  input.data.steps.a = step('program', 'running')
  const after = workflowLayout(workflowOf(input)!)
  expect(before.nodes[0]!.position.y).toBe(before.nodes[1]!.position.y)
  expect(after.nodes.map(n => [n.id, n.position])).toEqual(before.nodes.map(n => [n.id, n.position]))
  expect(after.nodes[0]!.data.status).toBe('running')
  expect(before.nodes[0]!.data.status).toBe('pending')
})

test('invalid or cross-plan edges and cycles never become invented connections', () => {
  expect(workflowOf(artifact({ a: step() }, [{ source: 'foreign', target: 'a' }]))).toBeNull()
  expect(workflowOf(artifact({ a: step(), b: step() }, [{ source: 'a', target: 'b' }, { source: 'b', target: 'a' }]))).toBeNull()
})

test('protocols, phases and states read in the user\'s words; a step keeps its own title and the owner\'s sentence', () => {
  const flow = workflowOf(artifact({ a: { ...step('law', 'needs_evidence'), title: '시설 기준 확인', code: 'law_evidence_only', message: '조례 원문이 필요해요.' }, b: step('program', 'running') }, [{ source: 'a', target: 'b' }]))!
  expect(protocolLabel('mesh')).toBe('필요한 것만 이어서')
  expect(protocolLabel('evaluator_optimizer')).toBe('제안 → 검토 → 수정 → 재검증')
  expect(phaseLabel('verify')).toBe('검증')
  expect(phaseLabel('lookup')).toBe('조회')
  expect(stepStatus('needs_evidence')).toEqual({ label: '근거 필요', tone: 'attention' })
  // A reading that could only hand back text (the Orchestrator's law_evidence_only) did its work.
  expect(stepStatus('needs_evidence', 'law_evidence_only')).toEqual({ label: '원문 확인', tone: 'confirmed' })
  expect(stepStatus('succeeded', 'law_evidence_only')).toEqual({ label: '완료', tone: 'confirmed' })
  expect(workflowStatus({ ...flow, status: 'needs_evidence' })).toEqual({ label: '근거 보완 필요', tone: 'attention' })
  expect(flow.steps.a).toMatchObject({ title: '시설 기준 확인', code: 'law_evidence_only', message: '조례 원문이 필요해요.' })
  expect(stepTitle(flow.steps.a!)).toBe('시설 기준 확인')
  expect(stepTitle({ ...flow.steps.b!, title: undefined, tool: 'law_facility_criteria' })).toBe('facility criteria')
  expect(stepOrder(flow)).toEqual(['a', 'b'])
  // Step a only fetched text (law_evidence_only): it counts as done while b still runs.
  expect(workflowStatus({ ...flow, status: 'running' })).toEqual({ label: '1/2 진행 중', tone: 'neutral' })
})
