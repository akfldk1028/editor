/** Orchestrator run door — the implementation lives in the shared `lib/orchestrator-runs`; this keeps the dialogue feature's imports. */
export { getRun, getRunContext, listRuns, parseRun, RunRequestError, submitHealth, submitRun } from '@/lib/orchestrator-runs/api'
export type { RunContext, RunRequest, RunSummary } from '@/lib/orchestrator-runs/types'
