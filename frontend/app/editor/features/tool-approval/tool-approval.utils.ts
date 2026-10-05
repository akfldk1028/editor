import type { ToolApproval, ToolIcon } from './tool-approval.types'
import { TOOL_ICON_MAP, TOOL_APPROVAL_PATTERN } from './tool-approval.constants'

let _counter = 0

/** Classify a tool name into an icon category */
export function classifyToolIcon(toolName: string): ToolIcon {
  const lower = toolName.toLowerCase()
  // Check exact match first
  if (TOOL_ICON_MAP[lower]) return TOOL_ICON_MAP[lower]
  // Check partial match
  for (const [key, icon] of Object.entries(TOOL_ICON_MAP)) {
    if (lower.includes(key)) return icon
  }
  return 'generic'
}

/**
 * Parse an input_request prompt into a ToolApproval if it matches
 * the tool approval pattern. Returns null for regular input requests.
 */
export function parseToolApproval(prompt: string, source: string): ToolApproval | null {
  const match = prompt.match(TOOL_APPROVAL_PATTERN)
  if (!match?.[1]) return null

  const toolName = match[1]
  const args = (match[2] ?? '').trim()

  return {
    id: `tool-${Date.now()}-${++_counter}`,
    toolName,
    args,
    icon: classifyToolIcon(toolName),
    source,
    timestamp: new Date().toISOString(),
    status: 'pending',
  }
}
