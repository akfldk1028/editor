import { describe, it, expect } from 'bun:test'
import { formatExport, getExportFilename } from './export.utils'
import type { AgentTurn } from '@/features/playground/executionStore'

const mockTurns: AgentTurn[] = [
  { source: 'User', content: 'Hello', timestamp: '2026-02-18T10:00:00Z', messageType: 'user' },
  { source: 'assistant', content: 'Hi there!', timestamp: '2026-02-18T10:00:01Z', messageType: 'agent', tokensIn: 10, tokensOut: 5 },
]

describe('formatExport', () => {
  it('formats as markdown', () => {
    const result = formatExport(mockTurns, 'TestTeam', 'markdown')
    expect(result).toContain('# Conversation Export')
    expect(result).toContain('**Team**: TestTeam')
    expect(result).toContain('### User')
    expect(result).toContain('Hello')
    expect(result).toContain('### assistant')
    expect(result).toContain('Hi there!')
  })

  it('formats as json', () => {
    const result = formatExport(mockTurns, 'TestTeam', 'json')
    const parsed = JSON.parse(result)
    expect(parsed.team).toBe('TestTeam')
    expect(parsed.turns).toHaveLength(2)
    expect(parsed.turns[0].content).toBe('Hello')
  })

  it('skips llm_event turns', () => {
    const turns: AgentTurn[] = [
      ...mockTurns,
      { source: 'llm', content: '{}', timestamp: '', messageType: 'llm_event' },
    ]
    const result = formatExport(turns, 'Test', 'json')
    const parsed = JSON.parse(result)
    expect(parsed.turns).toHaveLength(2)
  })
})

describe('getExportFilename', () => {
  it('generates markdown filename', () => {
    const name = getExportFilename('My Team', 'markdown')
    expect(name).toMatch(/^My_Team_\d{4}-\d{2}-\d{2}\.md$/)
  })

  it('generates json filename', () => {
    const name = getExportFilename('Test', 'json')
    expect(name).toMatch(/^Test_\d{4}-\d{2}-\d{2}\.json$/)
  })

  it('sanitizes special characters', () => {
    const name = getExportFilename('Test/Team<>:"|?*', 'markdown')
    expect(name).not.toContain('/')
    expect(name).not.toContain('<')
  })
})
