/**
 * Feed lines, one module per speaker under `lines/` (orchestrator, site, law, revision; `shared`
 * for what they have in common). This barrel keeps the import path; a new agent adds `lines/<id>.ts`
 * and re-exports here.
 */
export { answerLine, askFailedLine, askLines, landAnalysisLine, landAnalysisLines, lawBasisLine, lawCard, lawLine, limitsCard } from './lines/law'
export {
  connectionLine, evidenceCard, relayLine, requestFailedLine, requestingLines, resultLine, resultPrompt, type SelectedSite, selectedLine, selectedPrompt,
  type StepChange, stepChanges, stepState, stepTone, submittedLine,
} from './lines/orchestrator'
export { revisionLine } from './lines/revision'
export type { LawTarget } from './lines/shared'
export { siteFactsLine } from './lines/site'
