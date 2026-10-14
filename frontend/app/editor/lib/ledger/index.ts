/**
 * The 협업 장부 as the browser reads it: every call between the person, the Orchestrator and the agents, from the
 * backend's ledger (`/platform/ledger/hops`), tailed live. The collaboration flow and the conversation both read
 * it through here; neither reaches into the other.
 *
 *     types.ts      LedgerMessage: one request or answer, as the flow and the chat draw it
 *     api.ts        the first read and the live tail (SSE)
 *     hops.ts       ledger rows → messages; the scope query
 *     useLedger.ts  one shared tail per scope per page
 *     steps.ts      who the conversation waits on; what each agent was asked in a turn
 */
export { fullHopText, hopOf, listHops, openHopStream } from './api'
export { fromHops, hopText, type LedgerScope, scopeQuery } from './hops'
export { type TurnStep, turnSteps, waitingLine } from './steps'
export type { Direction, LedgerMessage } from './types'
export { type LedgerLoad, useLedger } from './useLedger'
