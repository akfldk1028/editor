import type { ModelEntry } from './model-registry.types'
import type { Component, ModelConfig } from '@/lib/contracts/workspace'

/** Convert a ModelEntry to an AutoGen Studio Component<ModelConfig> */
export function entryToComponent(entry: ModelEntry): Component<ModelConfig> {
  return {
    provider: entry.provider,
    component_type: 'model',
    version: 1,
    label: entry.label,
    description: entry.description ?? null,
    config: {
      model: entry.model,
      model_info: {
        vision: entry.capabilities.vision,
        function_calling: entry.capabilities.functionCalling,
        json_output: entry.capabilities.jsonOutput,
        family: entry.family,
      },
    } as ModelConfig,
  }
}

/** Filter models by search query (matches label, model id, family) */
export function filterModels(models: ModelEntry[], query: string): ModelEntry[] {
  if (!query.trim()) return models
  const q = query.toLowerCase()
  return models.filter(
    (m) =>
      m.label.toLowerCase().includes(q) ||
      m.model.toLowerCase().includes(q) ||
      m.family.toLowerCase().includes(q),
  )
}

/** Extract model id from a Component<ModelConfig> */
export function getModelId(component: Component<ModelConfig> | undefined): string | undefined {
  if (!component?.config) return undefined
  return (component.config as unknown as Record<string, unknown>)?.model as string | undefined
}
