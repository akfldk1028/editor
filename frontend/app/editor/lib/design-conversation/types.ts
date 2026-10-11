export interface ConversationMessage {
  id: string
  role: 'user' | 'assistant'
  agent: string | null
  text: string
  at: string
}

export interface ConversationArtifact {
  id: string
  owner: string
  title: string
  data: Record<string, unknown>
  status: string
}

export interface ConversationSnapshot {
  conversation_id: string
  revision: number
  status: 'idle' | 'working' | 'failed'
  messages: ConversationMessage[]
  artifacts: ConversationArtifact[]
  error: string | null
}

export interface ConversationContext {
  pnu?: string
  address?: string
  assessment_date?: string
  law_run_id?: string
}

export interface ConversationSubmission {
  conversation_id: string
  message_id: string
  text: string
  context: ConversationContext
  confirmation?: { artifact_id: string; context_hash: string }
}
