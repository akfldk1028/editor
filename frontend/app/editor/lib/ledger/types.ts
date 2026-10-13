import type { Communication } from '@/lib/orchestrator-runs/types'

export type Direction = 'request' | 'response'

/** One thing said between two parties: a caller's request to an agent, or that agent's answer. */
export interface LedgerMessage {
  id: string
  step: number
  direction: Direction
  from: string
  to: string
  tool: string
  state: string
  transport: Communication['transport']
  truncated: boolean
  text: string
  /** The A2A task this call ran as, when the record carries it: the key to the agent's own full copy. */
  a2a_task_id?: string | null
  /** When it happened (epoch ms), where the source says: the ledger's clock, the feed's, the saved conversation's. */
  at?: number
}
