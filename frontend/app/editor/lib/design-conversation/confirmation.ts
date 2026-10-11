import type { ConversationArtifact, ConversationSubmission } from './types'

export function confirmationFor(artifact: ConversationArtifact): ConversationSubmission['confirmation'] {
  const { data } = artifact
  const object = (value: unknown) => !!value && typeof value === 'object' && !Array.isArray(value)
  if (artifact.status !== 'awaiting_confirmation' || data.kind !== 'intent_reconfirmation' ||
    typeof data.context_hash !== 'string' || !/^[a-f0-9]{64}$/.test(data.context_hash) ||
    !object(data.context) || !object(data.proposed_intent)) return undefined
  return { artifact_id: artifact.id, context_hash: data.context_hash }
}
