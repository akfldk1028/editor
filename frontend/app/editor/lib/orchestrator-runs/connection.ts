import { getOrchestratorConnection } from './api'
import { postFeed } from './feed'
import { connectionLine, type SelectedSite, selectedLine, selectedPrompt } from './feed-lines'

/**
 * After 이 대지로 선택 saved: the user's bubble says which site, the Orchestrator answers whether it is
 * up and how many agents are (`/platform/status?refresh=1`), and when it is, asks what to do next —
 * nothing starts until the user chooses. Never throws; an unreachable backend reads as "down".
 */
export async function announceSiteSelected(site: SelectedSite, signal?: AbortSignal): Promise<void> {
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
  if (up) postFeed(selectedPrompt(site))
}
