import { describe, it, expect } from 'bun:test'
import { getUsagePercentage, getUsageLevel, formatTokenCount } from './context-usage.utils'

describe('getUsagePercentage', () => {
  it('returns 0 for zero tokens', () => {
    expect(getUsagePercentage(0, 128_000)).toBe(0)
  })

  it('calculates correct percentage', () => {
    expect(getUsagePercentage(64_000, 128_000)).toBe(50)
  })

  it('caps at 100%', () => {
    expect(getUsagePercentage(200_000, 128_000)).toBe(100)
  })

  it('returns 0 for zero limit', () => {
    expect(getUsagePercentage(1000, 0)).toBe(0)
  })
})

describe('getUsageLevel', () => {
  it('returns normal for low usage', () => {
    expect(getUsageLevel(30)).toBe('normal')
  })

  it('returns warning above 70%', () => {
    expect(getUsageLevel(75)).toBe('warning')
  })

  it('returns danger above 90%', () => {
    expect(getUsageLevel(95)).toBe('danger')
  })

  it('returns normal at exactly 70%', () => {
    expect(getUsageLevel(70)).toBe('normal')
  })
})

describe('formatTokenCount', () => {
  it('formats small numbers', () => {
    expect(formatTokenCount(500)).toBe('500')
  })

  it('formats thousands', () => {
    expect(formatTokenCount(37_000)).toBe('37K')
  })

  it('formats thousands with decimals', () => {
    expect(formatTokenCount(37_500)).toBe('37.5K')
  })

  it('formats millions', () => {
    expect(formatTokenCount(1_200_000)).toBe('1.2M')
  })

  it('formats even millions without .0', () => {
    expect(formatTokenCount(2_000_000)).toBe('2M')
  })

  it('formats even thousands without .0', () => {
    expect(formatTokenCount(5_000)).toBe('5K')
  })
})
