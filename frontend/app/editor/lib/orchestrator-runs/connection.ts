import { getOrchestratorConnection } from './api'
import { postFeed } from './feed'
import { connectionLine, type SelectedSite, selectedLine } from './feed-lines'

/**
 * After 이 대지로 선택 saved: the user's bubble says which site, then the Orchestrator answers whether it
 * is up and how many agents are (`/platform/status?refresh=1`). Never throws; an unreachable backend
 * reads as "down".
 */
export async function announceSiteSelected(site: SelectedSite, signal?: AbortSignal): Promise<void> {
  postFeed({ kind: 'user', text: selectedLine(site) })
  try {
    postFeed(connectionLine(await getOrchestratorConnection(true, signal)))
  } catch {
    if (signal?.aborted) return
    postFeed(connectionLine({ state: 'down', agentsUp: 0, agentsTotal: 0 }))
  }
}
