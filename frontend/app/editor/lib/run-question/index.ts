/**
 * What a waiting run asks the person, shared by every place a run is shown (the law panel, the conversation):
 * `lots.ts` reads a district lot question into choices (pure), `ui/LotQuestion.tsx` shows them and answers the run.
 */
export { asksForLot, type LotChoice, lotChoices } from './lots'
export { LotQuestion } from './ui/LotQuestion'
