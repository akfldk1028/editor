import { memo, useState, useCallback, useRef, useEffect } from 'react'
import { Download } from 'lucide-react'
import type { AgentTurn } from '@/features/playground/executionStore'
import type { ExportFormat } from '../export.types'
import { formatExport, downloadFile, getExportFilename } from '../export.utils'

interface ExportButtonProps {
  turns: AgentTurn[]
  teamName: string
  disabled?: boolean
}

const MIME_TYPES: Record<ExportFormat, string> = {
  markdown: 'text/markdown',
  json: 'application/json',
}

export const ExportButton = memo(function ExportButton({
  turns,
  teamName,
  disabled,
}: ExportButtonProps) {
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  // Close menu on outside click
  useEffect(() => {
    if (!menuOpen) return
    function handleClick(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [menuOpen])

  const handleExport = useCallback(
    (format: ExportFormat) => {
      const content = formatExport(turns, teamName, format)
      const filename = getExportFilename(teamName, format)
      downloadFile(content, filename, MIME_TYPES[format])
      setMenuOpen(false)
    },
    [turns, teamName],
  )

  const noTurns = turns.length === 0

  return (
    <div className="relative" ref={menuRef}>
      <button
        type="button"
        onClick={() => setMenuOpen((p) => !p)}
        disabled={disabled || noTurns}
        className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs border border-(--color-border-default) hover:bg-(--color-background-secondary) text-(--color-text-secondary) hover:text-(--color-text-primary) transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
        aria-label="Export conversation"
        aria-expanded={menuOpen}
      >
        <Download className="w-3.5 h-3.5" />
        Export
      </button>

      {menuOpen && (
        <div className="absolute right-0 top-full mt-1 w-40 rounded-lg border border-(--color-border-default) bg-(--color-surface-card) shadow-lg z-20 overflow-hidden">
          <button
            type="button"
            onClick={() => handleExport('markdown')}
            className="w-full text-left px-3 py-2 text-sm text-(--color-text-primary) hover:bg-(--color-background-secondary) transition-colors"
          >
            Markdown (.md)
          </button>
          <button
            type="button"
            onClick={() => handleExport('json')}
            className="w-full text-left px-3 py-2 text-sm text-(--color-text-primary) hover:bg-(--color-background-secondary) transition-colors"
          >
            JSON (.json)
          </button>
        </div>
      )}
    </div>
  )
})
