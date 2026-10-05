export type ProviderFamily = 'openai' | 'anthropic' | 'google' | 'azure' | 'local' | 'custom'

export interface ModelEntry {
  id: string
  label: string
  model: string
  provider: string
  family: ProviderFamily
  capabilities: ModelCapabilities
  description?: string
}

export interface ModelCapabilities {
  vision: boolean
  functionCalling: boolean
  jsonOutput: boolean
  streaming: boolean
}

export interface ProviderGroup {
  family: ProviderFamily
  label: string
  icon: string
  models: ModelEntry[]
}
