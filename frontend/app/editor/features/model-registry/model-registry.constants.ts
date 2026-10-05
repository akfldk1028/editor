import type { ModelEntry, ProviderGroup, ProviderFamily } from './model-registry.types'

// Provider metadata for grouping / display
export const PROVIDER_META: Record<ProviderFamily, { label: string; icon: string }> = {
  openai: { label: 'OpenAI', icon: '🟢' },
  anthropic: { label: 'Anthropic', icon: '🟠' },
  google: { label: 'Google', icon: '🔵' },
  azure: { label: 'Azure OpenAI', icon: '☁️' },
  local: { label: 'Local / Ollama', icon: '🖥️' },
  custom: { label: 'Custom', icon: '⚙️' },
}

// AutoGen Studio provider strings
const OPENAI_PROVIDER = 'autogen_ext.models.openai.OpenAIChatCompletionClient'
const ANTHROPIC_PROVIDER = 'autogen_ext.models.anthropic.AnthropicChatCompletionClient'

const FULL_CAPS = { vision: true, functionCalling: true, jsonOutput: true, streaming: true }
const TEXT_CAPS = { vision: false, functionCalling: true, jsonOutput: true, streaming: true }

/**
 * Comprehensive model registry.
 * Derived from JSON_MODULES/registry.json + major provider offerings.
 */
export const MODEL_REGISTRY: ModelEntry[] = [
  // --- OpenAI ---
  {
    id: 'gpt-4o',
    label: 'GPT-4o',
    model: 'gpt-4o',
    provider: OPENAI_PROVIDER,
    family: 'openai',
    capabilities: FULL_CAPS,
  },
  {
    id: 'gpt-4o-mini',
    label: 'GPT-4o Mini',
    model: 'gpt-4o-mini',
    provider: OPENAI_PROVIDER,
    family: 'openai',
    capabilities: FULL_CAPS,
  },
  {
    id: 'gpt-4.1',
    label: 'GPT-4.1',
    model: 'gpt-4.1',
    provider: OPENAI_PROVIDER,
    family: 'openai',
    capabilities: FULL_CAPS,
  },
  {
    id: 'gpt-4.1-mini',
    label: 'GPT-4.1 Mini',
    model: 'gpt-4.1-mini',
    provider: OPENAI_PROVIDER,
    family: 'openai',
    capabilities: FULL_CAPS,
  },
  {
    id: 'gpt-4.1-nano',
    label: 'GPT-4.1 Nano',
    model: 'gpt-4.1-nano',
    provider: OPENAI_PROVIDER,
    family: 'openai',
    capabilities: FULL_CAPS,
  },
  {
    id: 'o3',
    label: 'o3',
    model: 'o3',
    provider: OPENAI_PROVIDER,
    family: 'openai',
    capabilities: FULL_CAPS,
  },
  {
    id: 'o3-mini',
    label: 'o3 Mini',
    model: 'o3-mini',
    provider: OPENAI_PROVIDER,
    family: 'openai',
    capabilities: TEXT_CAPS,
  },
  {
    id: 'o4-mini',
    label: 'o4 Mini',
    model: 'o4-mini',
    provider: OPENAI_PROVIDER,
    family: 'openai',
    capabilities: FULL_CAPS,
  },

  // --- Anthropic ---
  {
    id: 'claude-opus-4',
    label: 'Claude Opus 4',
    model: 'claude-opus-4-20250514',
    provider: ANTHROPIC_PROVIDER,
    family: 'anthropic',
    capabilities: FULL_CAPS,
  },
  {
    id: 'claude-sonnet-4',
    label: 'Claude Sonnet 4',
    model: 'claude-sonnet-4-20250514',
    provider: ANTHROPIC_PROVIDER,
    family: 'anthropic',
    capabilities: FULL_CAPS,
  },
  {
    id: 'claude-haiku-4',
    label: 'Claude Haiku 4.5',
    model: 'claude-haiku-4-5-20251001',
    provider: ANTHROPIC_PROVIDER,
    family: 'anthropic',
    capabilities: FULL_CAPS,
  },
  {
    id: 'claude-opus-4.5',
    label: 'Claude Opus 4.5',
    model: 'claude-opus-4-5-20251101',
    provider: ANTHROPIC_PROVIDER,
    family: 'anthropic',
    capabilities: FULL_CAPS,
    description: 'Max OAuth',
  },
  {
    id: 'claude-sonnet-4.5',
    label: 'Claude Sonnet 4.5',
    model: 'claude-sonnet-4-5-20250929',
    provider: ANTHROPIC_PROVIDER,
    family: 'anthropic',
    capabilities: FULL_CAPS,
    description: 'Max OAuth',
  },

  // --- Google ---
  {
    id: 'gemini-2.5-pro',
    label: 'Gemini 2.5 Pro',
    model: 'gemini-2.5-pro',
    provider: OPENAI_PROVIDER,
    family: 'google',
    capabilities: FULL_CAPS,
    description: 'Via OpenAI-compatible endpoint',
  },
  {
    id: 'gemini-2.5-flash',
    label: 'Gemini 2.5 Flash',
    model: 'gemini-2.5-flash',
    provider: OPENAI_PROVIDER,
    family: 'google',
    capabilities: FULL_CAPS,
  },
  {
    id: 'gemini-2.0-flash',
    label: 'Gemini 2.0 Flash',
    model: 'gemini-2.0-flash',
    provider: OPENAI_PROVIDER,
    family: 'google',
    capabilities: FULL_CAPS,
  },

  // --- Azure ---
  {
    id: 'azure-gpt-4o',
    label: 'Azure GPT-4o',
    model: 'gpt-4o',
    provider: 'autogen_ext.models.openai.AzureOpenAIChatCompletionClient',
    family: 'azure',
    capabilities: FULL_CAPS,
  },
  {
    id: 'azure-gpt-4o-mini',
    label: 'Azure GPT-4o Mini',
    model: 'gpt-4o-mini',
    provider: 'autogen_ext.models.openai.AzureOpenAIChatCompletionClient',
    family: 'azure',
    capabilities: FULL_CAPS,
  },

  // --- Local / Ollama ---
  {
    id: 'mistral-7b',
    label: 'Mistral 7B',
    model: 'mistral:7b-instruct',
    provider: OPENAI_PROVIDER,
    family: 'local',
    capabilities: TEXT_CAPS,
    description: 'Ollama',
  },
  {
    id: 'llama-3.3',
    label: 'Llama 3.3 70B',
    model: 'llama3.3:70b',
    provider: OPENAI_PROVIDER,
    family: 'local',
    capabilities: TEXT_CAPS,
    description: 'Ollama',
  },
  {
    id: 'qwen-2.5',
    label: 'Qwen 2.5 72B',
    model: 'qwen2.5:72b',
    provider: OPENAI_PROVIDER,
    family: 'local',
    capabilities: TEXT_CAPS,
    description: 'Ollama',
  },
  {
    id: 'deepseek-v3',
    label: 'DeepSeek V3',
    model: 'deepseek-chat',
    provider: OPENAI_PROVIDER,
    family: 'local',
    capabilities: TEXT_CAPS,
    description: 'DeepSeek API',
  },
]

/** Group models by provider family */
export function groupByProvider(models: ModelEntry[]): ProviderGroup[] {
  const map = new Map<ProviderFamily, ModelEntry[]>()
  for (const m of models) {
    const arr = map.get(m.family) ?? []
    arr.push(m)
    map.set(m.family, arr)
  }
  const order: ProviderFamily[] = ['openai', 'anthropic', 'google', 'azure', 'local', 'custom']
  return order
    .filter((f) => map.has(f))
    .map((f) => ({
      family: f,
      label: PROVIDER_META[f].label,
      icon: PROVIDER_META[f].icon,
      models: map.get(f)!,
    }))
}
