/**
 * Feed lines, each in its speaker's folder (`lib/agents/<id>/lib/lines.ts`). This barrel keeps the
 * import path for the hooks and features; a new agent with turns adds its lines file and re-exports here.
 */
export {
  answerLine, askFailedLine, askLines, askRolePrompt, handoffLine, landAnalysisLine, landAnalysisLines, lawBasisLine, lawCard, lawLine, limitsCard,
} from '@/lib/agents/law/lib/lines'
export {
  connectionLine, evidenceCard, relayLine, requestFailedLine, requestingLines, resultLine, resultPrompt, type SelectedSite, selectedLine, selectedPrompt,
  type StepChange, stepChanges, stepState, stepTone, submittedLine,
} from '@/lib/agents/orchestrator/lib/lines'
export { revisionLine } from '@/lib/agents/revision/lib/lines'
export { siteFactsLine } from '@/lib/agents/site/lib/lines'
export type { LawTarget } from './law-target'
