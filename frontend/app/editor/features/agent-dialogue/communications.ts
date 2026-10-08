/** Run communications — the parser lives in the shared `lib/orchestrator-runs`; this keeps the dialogue feature's imports. */
export { parseCommunications } from '@/lib/orchestrator-runs/api'
export type { Communication, Communications } from '@/lib/orchestrator-runs/types'
