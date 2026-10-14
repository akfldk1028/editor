import type { ConversationArtifact, ConversationSubmission } from './types'

export function confirmationFor(artifact: ConversationArtifact): ConversationSubmission['confirmation'] {
  const { data } = artifact
  const object = (value: unknown) => !!value && typeof value === 'object' && !Array.isArray(value)
  const supported = data.kind === 'intent_reconfirmation' ? object(data.proposed_intent)
    : data.kind === 'layout_selection' && typeof data.candidate_id === 'string' && object(data.candidate)
  if (artifact.status !== 'awaiting_confirmation' || !supported ||
    typeof data.context_hash !== 'string' || !/^[a-f0-9]{64}$/.test(data.context_hash) ||
    !object(data.context)) return undefined
  return { artifact_id: artifact.id, context_hash: data.context_hash }
}
