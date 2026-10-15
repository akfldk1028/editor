import type { ConversationArtifact } from './types'

/**
 * The Orchestrator's record of one multi-owner workflow (orchestrator/cooperation): which protocol ran, each owner's
 * step and its state. The chat card and the flow read the same artifact, so both say the same thing at the same time.
 */
export type WorkflowStep = { owner: string; tool: string; phase: string; status: string; title?: string; code?: string; message?: string }
export type Workflow = { id: string; protocol: string; status: string; revision: number; steps: Record<string, WorkflowStep>; edges: { source: string; target: string }[] }
const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v)
const text = (v: unknown) => (typeof v === 'string' && v.trim() ? v : undefined)

/** The protocols the Orchestrator can run (cooperation/policy.PROTOCOLS), each in the user's words. */
export const PROTOCOLS: Record<string, string> = {
  sequential: '순서대로', parallel: '동시에', star: '모아서 종합', mesh: '필요한 것만 이어서', debate: '제안 → 독립 검토 → 수정',
  evaluator_optimizer: '제안 → 검토 → 수정 → 재검증',
}
export const PHASES: Record<string, string> = { propose: '제안', review: '검토', revise: '수정', verify: '검증' }
export const protocolLabel = (protocol: string) => PROTOCOLS[protocol] ?? '협업'
export const phaseLabel = (phase: string) => PHASES[phase] ?? phase

/** The Orchestrator's mark on a Law reading that only fetched statute or ordinance text: the text is real, no legal determination was asked. */
const EVIDENCE_ONLY = 'law_evidence_only'

/** A step that did its work: it succeeded, or it was a reading that could only ever hand back text. */
export const stepDone = (step: Pick<WorkflowStep, 'status' | 'code'>) => step.status === 'succeeded' || (step.status === 'needs_evidence' && step.code === EVIDENCE_ONLY)

/** A step's state as a word and a tone; the owner's own sentence, when it sent one, is `message`. */
export function stepStatus(status: string, code?: string): { label: string; tone: 'neutral' | 'attention' | 'confirmed' | 'running' } {
  if (stepDone({ status, code })) return status === 'succeeded' ? { label: '완료', tone: 'confirmed' } : { label: '원문 확인', tone: 'confirmed' }
  switch (status) {
    case 'pending': return { label: '대기', tone: 'neutral' }
    case 'running': return { label: '진행 중', tone: 'running' }
    case 'succeeded': return { label: '완료', tone: 'confirmed' }
    case 'needs_evidence': return { label: '근거 필요', tone: 'attention' }
    case 'needs_revision': return { label: '수정 필요', tone: 'attention' }
    case 'blocked': return { label: '앞 단계에서 멈춤', tone: 'attention' }
    case 'failed': return { label: '실패', tone: 'attention' }
    default: return { label: '상태 미확인', tone: 'neutral' }
  }
}

/** The workflow as a whole: what the person sees on the card's edge. */
export function workflowStatus(flow: Workflow): { label: string; tone: 'neutral' | 'attention' | 'confirmed' } {
  const steps = Object.values(flow.steps)
  const done = steps.filter(stepDone).length
  switch (flow.status) {
    case 'running': return { label: `${done}/${steps.length} 진행 중`, tone: 'neutral' }
    case 'completed': return { label: '완료', tone: 'confirmed' }
    case 'needs_evidence': return { label: '근거 보완 필요', tone: 'attention' }
    case 'needs_revision': return { label: '수정 필요', tone: 'attention' }
    case 'blocked': return { label: '중간에 멈춤', tone: 'attention' }
    case 'failed': return { label: '실패', tone: 'attention' }
    default: return { label: '상태 미확인', tone: 'neutral' }
  }
}

/** A tool's name as a title when the record carries none: `law_facility_criteria` → "facility criteria". */
export const stepTitle = (step: WorkflowStep) => step.title ?? step.tool.replace(/^[a-z]+_/, '').replaceAll('_', ' ')

export function workflowOf(artifact: ConversationArtifact): Workflow | null {
  const d = artifact.data
  if (artifact.owner !== 'orchestrator' || !(String(d.protocol) in PROTOCOLS) || !record(d.steps) || !Array.isArray(d.edges)) return null
  const steps: Workflow['steps'] = {}
  for (const [id, value] of Object.entries(d.steps)) {
    if (!record(value) || !['owner', 'tool', 'phase', 'status'].every(key => typeof value[key] === 'string')) return null
    steps[id] = { owner: value.owner as string, tool: value.tool as string, phase: value.phase as string, status: value.status as string,
      title: text(value.title), code: text(value.code), message: text(value.message) }
  }
  const edges: Workflow['edges'] = []
  for (const edge of d.edges) {
    if (!record(edge) || typeof edge.source !== 'string' || typeof edge.target !== 'string' || !Object.hasOwn(steps, edge.source) || !Object.hasOwn(steps, edge.target)) return null
    edges.push({ source: edge.source, target: edge.target })
  }
  const remaining = new Set(Object.keys(steps)), done = new Set<string>()
  while (remaining.size) {
    const ready = [...remaining].filter(id => edges.filter(e => e.target === id).every(e => done.has(e.source)))
    if (!ready.length) return null
    ready.forEach(id => { remaining.delete(id); done.add(id) })
  }
  return { id: artifact.id, protocol: String(d.protocol), status: String(d.status ?? artifact.status), revision: typeof d.revision === 'number' ? d.revision : 0, steps, edges }
}

/** Steps in the order they could run: by rank (how many steps had to finish first), then as recorded. */
export function stepOrder(flow: Workflow): string[] {
  const ranks = new Map<string, number>()
  const rank = (id: string): number => {
    if (ranks.has(id)) return ranks.get(id)!
    const parents = flow.edges.filter(e => e.target === id)
    const value = parents.length ? Math.max(...parents.map(e => rank(e.source))) + 1 : 0
    ranks.set(id, value)
    return value
  }
  const ids = Object.keys(flow.steps)
  ids.forEach(rank)
  return [...ids].sort((a, b) => ranks.get(a)! - ranks.get(b)!)
}

export function workflowLayout(flow: Workflow) {
  const ids = stepOrder(flow)
  const ranks = new Map<string, number>()
  for (const id of ids) {
    const parents = flow.edges.filter(e => e.target === id)
    ranks.set(id, parents.length ? Math.max(...parents.map(e => ranks.get(e.source)!)) + 1 : 0)
  }
  return {
    nodes: Object.keys(flow.steps).map(id => {
      const level = Object.keys(flow.steps).filter(other => ranks.get(other) === ranks.get(id))
      return { id, position: { x: (level.indexOf(id) - (level.length - 1) / 2) * 290, y: ranks.get(id)! * 170 }, data: { ...flow.steps[id]! } }
    }),
    edges: flow.edges.map((edge, index) => ({ ...edge, id: `${edge.source}:${edge.target}:${index}` })),
  }
}
