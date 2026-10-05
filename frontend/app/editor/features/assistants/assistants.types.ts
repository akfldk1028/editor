export interface AssistantPreset {
  id: string
  avatar: string
  nameI18n: Record<string, string>
  descriptionI18n: Record<string, string>
  promptsI18n: Record<string, string[]>
  skills: string[]
  /** Recommended team pattern (e.g., 'RoundRobinGroupChat', 'SelectorGroupChat') */
  pattern?: string
  /** Recommended model id from model-registry */
  recommendedModel?: string
  /** Category for filter tabs */
  category: 'productivity' | 'creative' | 'development' | 'lifestyle'
  /** System prompt template - injected when team is created from this preset */
  systemPromptI18n?: Record<string, string>
}

export interface SkillDefinition {
  id: string
  name: string
  description: string
  icon: string
  triggers: string[]
}
