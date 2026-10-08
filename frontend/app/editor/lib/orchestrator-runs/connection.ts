import { loadCapabilities } from '@/lib/goals'

import { getOrchestratorConnection } from './api'
import { postFeed } from './feed'
import { connectionLine, type SelectedSite, selectedLine, selectedPrompt } from './feed-lines'
import { setConversationSite } from './site-context'

/**
 * After 이 대지로 선택 saved: the user's bubble says which site, the Orchestrator answers whether it is
 * up and how many agents are (`/platform/status?refresh=1`), and when it is, asks what to do next
 * with the choices the goal catalog allows — nothing starts until the user chooses. Never throws; an
 * unreachable backend reads as "down".
 */
export async function announceSiteSelected(site: SelectedSite, signal?: AbortSignal): Promise<void> {
  const first = site.parcels[0]
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
