import { describe, it, expect } from 'bun:test'
import { entryToComponent, filterModels, getModelId } from './model-registry.utils'
import type { ModelEntry } from './model-registry.types'

const MOCK_ENTRY: ModelEntry = {
  id: 'gpt-4o',
  label: 'GPT-4o',
  model: 'gpt-4o',
  provider: 'autogen_ext.models.openai.OpenAIChatCompletionClient',
  family: 'openai',
  capabilities: { vision: true, functionCalling: true, jsonOutput: true, streaming: true },
}

describe('entryToComponent', () => {
  it('converts ModelEntry to Component', () => {
    const comp = entryToComponent(MOCK_ENTRY)
    expect(comp.provider).toBe(MOCK_ENTRY.provider)
    expect(comp.component_type).toBe('model')
    expect((comp.config as unknown as Record<string, unknown>).model).toBe('gpt-4o')
  })
})

describe('filterModels', () => {
  const models: ModelEntry[] = [
    MOCK_ENTRY,
    { ...MOCK_ENTRY, id: 'claude-opus', label: 'Claude Opus 4', model: 'claude-opus-4', family: 'anthropic' },
    { ...MOCK_ENTRY, id: 'mistral', label: 'Mistral 7B', model: 'mistral:7b', family: 'local' },
  ]

  it('returns all when query is empty', () => {
    expect(filterModels(models, '')).toHaveLength(3)
  })

  it('filters by label', () => {
    expect(filterModels(models, 'claude')).toHaveLength(1)
  })

  it('filters by family', () => {
    expect(filterModels(models, 'local')).toHaveLength(1)
  })

  it('is case-insensitive', () => {
    expect(filterModels(models, 'GPT')).toHaveLength(1)
  })
})

describe('getModelId', () => {
  it('extracts model from component', () => {
    const comp = entryToComponent(MOCK_ENTRY)
    expect(getModelId(comp)).toBe('gpt-4o')
  })

  it('returns undefined for missing component', () => {
    expect(getModelId(undefined)).toBeUndefined()
  })
})
