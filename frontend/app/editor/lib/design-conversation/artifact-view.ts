import type { ConversationArtifact } from './types'
import { workflowOf } from './workflow'

/**
 * What the chat shows of its cards: only what the person acts on - a card awaiting their confirmation or choice -
 * and the newest proposal. Workflow records, earlier proposals and stale cards are the collaboration panel's
 * business (흐름도 · 대화 기록 · 실행), never the chat's: a chat is questions and answers.
 */
export function chatArtifacts(artifacts: readonly ConversationArtifact[]): ConversationArtifact[] {
  const proposals = artifacts.filter((artifact) => workflowOf(artifact) === null)
  const newest = [...proposals].reverse().find((artifact) => artifact.status === 'proposed') ?? null
  return proposals.filter((artifact) => artifact.status === 'awaiting_confirmation' || artifact === newest)
}
