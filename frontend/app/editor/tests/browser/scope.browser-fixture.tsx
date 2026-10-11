import { createRoot } from 'react-dom/client'
import { flushSync } from 'react-dom'
import { useSiteRun } from '@/features/artifacts/site-map/model/useSiteRun'
import { useOrchestratorReview } from '@/features/artifacts/law/model/useOrchestratorReview'
import { useLawAnalysis } from '@/features/artifacts/law/model/useLawAnalysis'
import type { SavedSite } from '@/features/artifacts/site-map/lib/picks'
import { currentConversation, selectConversationProject } from '@/lib/design-conversation/session'
import { designConversationContext } from '@/lib/design-conversation/context'
import { announceSiteSelected } from '@/lib/orchestrator-runs/connection'
import { feed, feedForProject } from '@/lib/orchestrator-runs/feed'

let siteRun: ReturnType<typeof useSiteRun>
let review: ReturnType<typeof useOrchestratorReview>
let direct: ReturnType<typeof useLawAnalysis>
let enabled = false
let projectIds = ['a', 'b']
let mode: 'site' | 'review' | 'direct' = 'site'
let requestBody: Record<string, unknown> = {}
const requests: string[] = []
const site = { selection_id: 'selection-a', label: 'site A', total_area_m2: null, parcels: [{ pnu: 'parcel-a', address: 'address A' }] } as SavedSite
const conditions = { buildingType: '', floorAreaM2: null, assessmentDate: '2026-10-09' }
const run = () => ({ run_id: 'run-a', request_id: 'request-a', owner_project_id: 'owner-a', branch_id: 'main', goal: 'limits', status: mode === 'review' ? 'completed' : 'running', receipt_task_ids: [], pending_input: false })
window.fetch = async (input, init) => {
  const url = String(input)
  requests.push(url)
  if (url.endsWith('/projects')) return Response.json(projectIds.map((id) => ({ project_id: id, owner_project_id: id, branch_id: 'main', scene_id: id, scene_revision: 1, scene_project_id: null })))
  if (url.includes('/runs/latest')) return Response.json({}, { status: 404 })
  if (url.endsWith('/capabilities')) return Response.json({ goals: [{ id: 'limits', label: 'review', available: true, offer: true, owners: [] }] })
  if (url.endsWith('/host/status')) return Response.json({ agents: {} })
  if (url.endsWith('/host/ensure')) return Response.json({ up: ['law'], failed: [] })
  if (url.includes('/status?')) return Response.json({ orchestrator: { state: 'up' }, services: [] })
  if (url.endsWith('/context')) return Response.json({ scene_revision: 1, source_versions: {} })
  if (url.endsWith('/runs') && init?.method === 'POST') {
    requestBody = JSON.parse(String(init.body)).request
    return Response.json(run())
  }
  if (url.includes('/results?')) return Response.json({ run_id: 'run-a', status: 'completed', request: requestBody, steps: [], missing_evidence_all: [], law: { status: 'succeeded' } })
  if (url.includes('/runs/run-a?')) return Response.json(run())
  if (url.endsWith('/law-analysis')) return new Promise(() => {})
  return Response.json({})
}
function Site() { siteRun = useSiteRun(site, undefined); return null }
function Review() { review = useOrchestratorReview('parcel-a', 'address A', undefined); return null }
function Direct() { direct = useLawAnalysis({ pnu: 'parcel-a' }, conditions, enabled); return null }
const root = createRoot(document.getElementById('root')!)
const render = () => flushSync(() => root.render(mode === 'site' ? <Site /> : mode === 'review' ? <Review /> : <Direct />))
selectConversationProject('a')
render()
const harness = {
  mount(next: typeof mode) { mode = next; render() },
  switchProject(id: string) { flushSync(() => selectConversationProject(id)) },
  async start() { await (mode === 'site' ? siteRun.start() : review.start()) },
  state() { return mode === 'site' ? { chosen: siteRun.chosen?.project_id, phase: siteRun.phase.kind } : { chosen: review.chosen?.project_id, phase: review.phase.kind } },
  context: designConversationContext,
  requests: () => requests,
  enable(value: boolean) { enabled = value; render() },
  rerun() { direct.rerun() },
  setReviewDate(assessmentDate: string) { flushSync(() => review.setConditions({ ...review.conditions, assessmentDate })) },
  async firstSelection() {
    flushSync(() => root.render(null))
    selectConversationProject(null)
    projectIds = ['a']
    feed.clear()
    await announceSiteSelected(site)
    const selected = currentConversation()
    return { selected, entries: feedForProject(feed.get(), selected.projectId, selected.conversationId) }
  },
}
declare global { interface Window { conversationScopeHarness: typeof harness } }
window.conversationScopeHarness = harness
