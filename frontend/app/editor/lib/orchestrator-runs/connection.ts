import { loadCapabilities } from '@/lib/goals'

import { getOrchestratorConnection, listProjects } from './api'
import { currentConversation, selectConversationProject } from '@/lib/design-conversation/session'
import { rememberConversationSite } from '@/lib/design-conversation/context'
import { loadRunConditions } from './conditions'
import { projectFeed } from './feed'
import { connectionLine, type SelectedSite, selectedLine, selectedPrompt } from './feed-lines'
import { setConversationSite } from './site-context'
import { resolveProject } from './submit'

/**
 * After 이 대지로 선택 saved: the user's bubble says which site, the Orchestrator answers whether it is
 * up and how many agents are (`/platform/status?refresh=1`), and when it is, asks what to do next
 * with the choices the goal catalog allows — nothing starts until the user chooses. Never throws; an
 * unreachable backend reads as "down".
 */
export async function announceSiteSelected(site: SelectedSite, signal?: AbortSignal): Promise<void> {
  let projectId = currentConversation().projectId
  if (!projectId) {
    try {
      const choice = resolveProject(await listProjects(signal), undefined)
      if (signal?.aborted) return
      if (choice.kind === 'resolved') {
        const selected = currentConversation().projectId
        if (selected && selected !== choice.project.project_id) return
        selectConversationProject(choice.project.project_id)
        projectId = choice.project.project_id
      }
    } catch {
      if (signal?.aborted) return
    }
  }
  const postFeed = projectFeed(projectId)
  const first = site.parcels[0]
  if (projectId && first) rememberConversationSite(projectId, { pnu: first.pnu, address: first.address || site.label }, loadRunConditions().assessmentDate)
  setConversationSite(first ? { pnu: first.pnu, address: first.address || site.label } : null)
  postFeed({ kind: 'user', text: selectedLine(site) })
  let up = false
  try {
    const connection = await getOrchestratorConnection(true, signal)
    postFeed(connectionLine(connection))
    up = connection.state === 'up'
  } catch {
    if (signal?.aborted) return
    postFeed(connectionLine({ state: 'down', agentsUp: 0, agentsTotal: 0 }))
  }
  if (!up) return
  const capabilities = await loadCapabilities(signal)
  if (signal?.aborted) return
  postFeed(selectedPrompt(site, capabilities))
}
