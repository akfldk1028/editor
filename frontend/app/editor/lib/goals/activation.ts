/**
 * Who a goal still needs woken: the owners the host does not report up. Activation belongs to the call
 * (design: plans/agent-activation-design-20261009.md §4): the conversation asks the host to bring these up
 * before it submits, holding the request like KEDA's interceptor, and pre-warms them with a short lease the
 * moment the Orchestrator's ledger names the goal (§11.1).
 */
import { ensureAgents, getHostStatus } from '@/lib/orchestrator-runs/api'
import type { Goal, HostStatus } from '@/lib/orchestrator-runs/types'

/** Lease for a run the user asked for. */
export const RUN_LEASE_S = 1800
/** Lease for a speculative warm-up: the user may still not press the button. */
export const PREWARM_LEASE_S = 300

/** Owners not up, in owner order. An owner the host does not know (not in the registry) is left alone. */
export function neededAgents(goal: Pick<Goal, 'owners'>, status: HostStatus | null): string[] {
  if (!status) return []
  return goal.owners.filter((owner) => {
    const agent = status.agents[owner]
    return agent !== undefined && agent.state !== 'up'
  })
}

/** The host's view, or null when it cannot be read (the caller then submits without waking anyone). */
export async function hostStatus(signal?: AbortSignal): Promise<HostStatus | null> {
  try {
    return await getHostStatus(signal)
  } catch {
    return null
  }
}

/** Speculative: wake a goal's missing owners with a short lease; never throws, never waited for. */
export function prewarm(goal: Pick<Goal, 'owners'>, status: HostStatus | null): string[] {
  const needed = neededAgents(goal, status)
  if (needed.length) void ensureAgents(needed, PREWARM_LEASE_S).catch(() => undefined)
  return needed
}
