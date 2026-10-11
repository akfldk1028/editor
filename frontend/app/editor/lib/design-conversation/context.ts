import { conversationSite, setConversationSite, type ConversationSite } from '@/lib/orchestrator-runs/site-context'
import type { RunResults } from '@/lib/orchestrator-runs/types'
import type { ConversationContext } from './types'

const sites = new Map<string, ConversationContext>()
const lawRuns = new Map<string, string>()
let activeProject: string | null = null
const runKey = (project: string, pnu: string, date?: string | null) => JSON.stringify([project, pnu, date ?? null])

export function activateConversationContext(projectId: string | null) {
  activeProject = projectId
  const site = projectId ? sites.get(projectId) : undefined
  setConversationSite(site?.pnu ? { pnu: site.pnu, address: site.address ?? '' } : null)
}

export function rememberConversationSite(projectId: string, site: ConversationSite, assessmentDate?: string) {
  sites.set(projectId, { pnu: site.pnu, address: site.address, ...(assessmentDate ? { assessment_date: assessmentDate } : {}) })
  if (activeProject === projectId) setConversationSite(site)
}

export function rememberConversationLawRun(projectId: string, pnu: string, runId: string, results: Pick<RunResults, 'run_id' | 'request' | 'law' | 'status'>) {
  if (results.run_id !== runId || results.request?.pnu !== pnu || results.law?.status !== 'succeeded'
    || !['succeeded', 'completed', 'blocked'].includes(results.status)) return
  lawRuns.set(runKey(projectId, pnu, results.request.assessment_date), runId)
}

export function designConversationContext(projectId: string): ConversationContext {
  const scoped = sites.get(projectId)
  if (!scoped?.pnu) return {}
  const selected = conversationSite()
  const lawRun = lawRuns.get(runKey(projectId, scoped.pnu, scoped.assessment_date))
  return {
    ...scoped,
    ...(activeProject === projectId && selected?.pnu === scoped.pnu ? { address: selected.address } : {}),
    ...(lawRun ? { law_run_id: lawRun } : {}),
  }
}
