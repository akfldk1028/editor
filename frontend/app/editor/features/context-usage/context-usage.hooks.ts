import { useMemo } from 'react'
import type { AgentTurn } from '@/features/playground/executionStore'
import type { TokenUsage } from './context-usage.types'
import { DEFAULT_CONTEXT_LIMIT } from './context-usage.constants'
import { getUsagePercentage, getUsageLevel, formatTokenCount } from './context-usage.utils'

/** Aggregate token usage from turns */
export function useContextUsage(turns: AgentTurn[], contextLimit = DEFAULT_CONTEXT_LIMIT) {
  return useMemo(() => {
    const usage: TokenUsage = { totalIn: 0, totalOut: 0 }

    for (const turn of turns) {
      if (turn.tokensIn) usage.totalIn += turn.tokensIn
      if (turn.tokensOut) usage.totalOut += turn.tokensOut
    }

    const total = usage.totalIn + usage.totalOut
    const percentage = getUsagePercentage(total, contextLimit)
    const level = getUsageLevel(percentage)

    return {
      usage,
      total,
      percentage,
      level,
      displayTotal: formatTokenCount(total),
      displayLimit: formatTokenCount(contextLimit),
    }
  }, [turns, contextLimit])
}
