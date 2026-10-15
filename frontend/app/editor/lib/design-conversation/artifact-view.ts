import type { ConversationArtifact } from './types'
import { workflowOf } from './workflow'

/**
 * What the conversation shows of its cards: the work in progress and what waits for the person, in front; everything
 * earlier folded away. A chat that stacks every turn's workflow record and every old proposal under the latest
 * message is not a conversation.
 *
 * In front: workflows still running, the workflows of the latest turn (those sharing the newest record's run), cards
 * awaiting the person's confirmation or choice, and the newest proposal. The rest is the past.
 */
export function splitArtifacts(artifacts: readonly ConversationArtifact[]): { live: ConversationArtifact[]; past: ConversationArtifact[] } {
  const runOf = (artifact: ConversationArtifact) => (typeof artifact.data.run_id === 'string' ? artifact.data.run_id : null)
  const workflows = artifacts.filter((artifact) => workflowOf(artifact) !== null)
  const latestRun = workflows.length ? runOf(workflows[workflows.length - 1]!) : null
  const proposals = artifacts.filter((artifact) => workflowOf(artifact) === null)
  const newestProposal = [...proposals].reverse().find((artifact) => artifact.status === 'proposed') ?? null
  const live = new Set<ConversationArtifact>()
  for (const artifact of artifacts) {
    const flow = workflowOf(artifact)
    if (flow) {
      if (flow.status === 'running' || (latestRun !== null && runOf(artifact) === latestRun)) live.add(artifact)
    } else if (artifact.status === 'awaiting_confirmation' || artifact === newestProposal) live.add(artifact)
  }
  return { live: artifacts.filter((artifact) => live.has(artifact)), past: artifacts.filter((artifact) => !live.has(artifact)) }
}
