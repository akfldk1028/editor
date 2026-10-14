/**
 * What a waiting run asks the person, shared by every place a run is shown (the law panel, the conversation):
 * `form.ts` reads any question into its shape and fields, `lots.ts` a district lot question into choices (both pure);
 * `ui/QuestionCard.tsx` answers whichever it is in place (`ui/LotQuestion.tsx` for lots); `useWaitingQuestions` finds them.
 */
export { asksForLot, type LotChoice, lotChoices } from './lots'
export { answerLine, answerOf, fieldsOf, intentLines, type QuestionShape, shapeOf } from './form'
export { LotQuestion } from './ui/LotQuestion'
export { QuestionCard } from './ui/QuestionCard'
export { useWaitingQuestions, type WaitingQuestion } from './useWaitingQuestions'
