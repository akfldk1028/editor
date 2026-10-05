import type { AgentTurn } from '@/features/playground/executionStore'
import type { ExportFormat } from './export.types'

/** Convert turns to markdown format */
function turnsToMarkdown(turns: AgentTurn[], teamName: string): string {
  const lines: string[] = [
    `# Conversation Export`,
    `**Team**: ${teamName}`,
    `**Date**: ${new Date().toISOString()}`,
    `**Turns**: ${turns.length}`,
    '',
    '---',
    '',
  ]

  for (const turn of turns) {
    if (turn.messageType === 'llm_event') continue // Skip LLM events

    const time = turn.timestamp ? new Date(turn.timestamp).toLocaleTimeString() : ''
    const role = turn.messageType === 'user' ? 'User' : turn.source
    lines.push(`### ${role} ${time ? `(${time})` : ''}`)

    if (turn.tokensIn || turn.tokensOut) {
      lines.push(`> Tokens: ${turn.tokensIn ?? 0} in / ${turn.tokensOut ?? 0} out`)
    }

    lines.push('')
    lines.push(turn.content)
    lines.push('')
    lines.push('---')
    lines.push('')
  }

  return lines.join('\n')
}

/** Convert turns to JSON format */
function turnsToJson(turns: AgentTurn[], teamName: string): string {
  const data = {
    team: teamName,
    exportedAt: new Date().toISOString(),
    turnCount: turns.length,
    turns: turns
      .filter((t) => t.messageType !== 'llm_event')
      .map((t) => ({
        source: t.source,
        type: t.messageType,
        content: t.content,
        timestamp: t.timestamp,
        tokensIn: t.tokensIn ?? null,
        tokensOut: t.tokensOut ?? null,
      })),
  }
  return JSON.stringify(data, null, 2)
}

/** Format turns for export */
export function formatExport(turns: AgentTurn[], teamName: string, format: ExportFormat): string {
  return format === 'markdown'
    ? turnsToMarkdown(turns, teamName)
    : turnsToJson(turns, teamName)
}

/** Trigger browser download of a text file */
export function downloadFile(content: string, filename: string, mimeType: string): void {
  const blob = new Blob([content], { type: mimeType })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

/** Generate export filename */
export function getExportFilename(teamName: string, format: ExportFormat): string {
  const date = new Date().toISOString().slice(0, 10)
  const safeName = teamName.replace(/[^a-zA-Z0-9_-]/g, '_').slice(0, 30)
  const ext = format === 'markdown' ? 'md' : 'json'
  return `${safeName}_${date}.${ext}`
}
