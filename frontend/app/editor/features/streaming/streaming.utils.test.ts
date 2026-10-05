import { describe, it, expect } from 'bun:test'
import { stripThinkTags } from './streaming.utils'

describe('stripThinkTags', () => {
  it('removes complete think blocks', () => {
    expect(stripThinkTags('Hello <think>internal reasoning</think> World')).toBe('Hello  World')
  })

  it('removes multiple think blocks', () => {
    const input = '<think>a</think>Hello<think>b</think>World'
    expect(stripThinkTags(input)).toBe('HelloWorld')
  })

  it('removes multiline think blocks', () => {
    const input = 'Before\n<think>\nline1\nline2\n</think>\nAfter'
    expect(stripThinkTags(input)).toBe('Before\n\nAfter')
  })

  it('removes orphaned opening think tag at end', () => {
    expect(stripThinkTags('Hello <think>still thinking...')).toBe('Hello')
  })

  it('passes through content without think tags', () => {
    expect(stripThinkTags('No tags here')).toBe('No tags here')
  })

  it('handles empty string', () => {
    expect(stripThinkTags('')).toBe('')
  })
})
