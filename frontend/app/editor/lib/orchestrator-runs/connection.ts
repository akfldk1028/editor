import { getOrchestratorConnection } from './api'
import { postFeed } from './feed'
import { connectionLine, type SelectedSite, selectedLine } from './feed-lines'

/**
 * After 이 대지로 선택 saved: say which site, then ask the backend (`/platform/status?refresh=1`) whether the
 * Orchestrator answers and how many agents are up. Never throws; an unreachable backend reads as "down".
 */
export async function announceSiteSelected(site: SelectedSite, signal?: AbortSignal): Promise<void> {
  postFeed({ kind: 'system', text: selectedLine(site) })
  try {
    postFeed(connectionLine(await getOrchestratorConnection(true, signal)))
  } catch {
    if (signal?.aborted) return
    postFeed(connectionLine({ state: 'down', agentsUp: 0, agentsTotal: 0 }))
  }
}
