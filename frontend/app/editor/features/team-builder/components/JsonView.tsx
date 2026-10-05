/**
 * JsonView - JSON viewer with syntax highlighting, copy-to-clipboard, and edit mode
 * Supports read-only display and optional textarea editing for team configuration JSON
 */

import { Button } from '@/elements/workspace/index'
import { Check, Copy, Pencil } from 'lucide-react'
import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'

interface JsonViewProps {
  data: unknown
  editable?: boolean
  onChange?: (data: unknown) => void
}

/** Escape HTML entities to prevent XSS in dangerouslySetInnerHTML */
function escapeHtml(str: string): string {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

/** Simple regex-based JSON syntax highlighter (runs on escaped HTML) */
function highlightJson(json: string): string {
  return (
    escapeHtml(json)
      // Strings (keys and values)
      .replace(
        /("(?:\\.|[^"\\])*")\s*:/g,
        '<span class="text-(--color-text-secondary) font-medium">$1</span>:',
      )
      .replace(
        /:\s*("(?:\\.|[^"\\])*")/g,
        ': <span class="text-(--color-accent-primary)">$1</span>',
      )
      // Standalone strings (in arrays)
      .replace(
        /(?<=[\[,]\s*)("(?:\\.|[^"\\])*")(?=\s*[,\]])/g,
        '<span class="text-(--color-accent-primary)">$1</span>',
      )
      // Numbers
      .replace(/:\s*(\d+\.?\d*)/g, ': <span class="text-(--color-semantic-warning)">$1</span>')
      // Booleans
      .replace(/:\s*(true|false)/g, ': <span class="text-(--color-semantic-warning)">$1</span>')
      // Null
      .replace(/:\s*(null)/g, ': <span class="text-(--color-text-tertiary)">$1</span>')
  )
}

export const JsonView = memo(function JsonView({ data, editable, onChange }: JsonViewProps) {
  const [copied, setCopied] = useState(false)
  const [isEditMode, setIsEditMode] = useState(false)
  const [editText, setEditText] = useState('')
  const [parseError, setParseError] = useState<string | null>(null)
  const copyTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined)

  useEffect(() => {
    return () => clearTimeout(copyTimerRef.current)
  }, [])

  // Exit edit mode when editable prop becomes false
  useEffect(() => {
    if (!editable) {
      setIsEditMode(false)
      setParseError(null)
    }
  }, [editable])

  const jsonString = useMemo(() => JSON.stringify(data, null, 2), [data])

  const highlighted = useMemo(() => highlightJson(jsonString), [jsonString])

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(isEditMode ? editText : jsonString)
      setCopied(true)
      clearTimeout(copyTimerRef.current)
      copyTimerRef.current = setTimeout(() => setCopied(false), 2000)
    } catch {
      // Clipboard API unavailable in some environments
    }
  }, [jsonString, editText, isEditMode])

  const handleStartEdit = useCallback(() => {
    setEditText(jsonString)
    setParseError(null)
    setIsEditMode(true)
  }, [jsonString])

  const handleCancelEdit = useCallback(() => {
    setIsEditMode(false)
    setParseError(null)
  }, [])

  const handleApply = useCallback(() => {
    try {
      const parsed = JSON.parse(editText)
      onChange?.(parsed)
      setIsEditMode(false)
      setParseError(null)
    } catch (e) {
      setParseError(e instanceof Error ? e.message : 'Invalid JSON')
    }
  }, [editText, onChange])

  const handleFormat = useCallback(() => {
    try {
      const parsed = JSON.parse(editText)
      setEditText(JSON.stringify(parsed, null, 2))
      setParseError(null)
    } catch (e) {
      setParseError(e instanceof Error ? e.message : 'Invalid JSON')
    }
  }, [editText])

  return (
    <div className="relative" aria-label="Team configuration JSON">
      <div className="absolute top-2 right-2 z-10 flex gap-1">
        {editable && !isEditMode && (
          <Button size="sm" variant="ghost" onClick={handleStartEdit} aria-label="Edit JSON">
            <Pencil className="w-3.5 h-3.5 mr-1" />
            <span>Edit</span>
          </Button>
        )}
        {isEditMode && (
          <>
            <Button size="sm" variant="ghost" onClick={handleFormat} aria-label="Format JSON">
              Format
            </Button>
            <Button
              size="sm"
              variant="primary"
              onClick={handleApply}
              aria-label="Apply JSON changes"
            >
              Apply
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={handleCancelEdit}
              aria-label="Cancel editing"
            >
              Cancel
            </Button>
          </>
        )}
        <Button size="sm" variant="ghost" onClick={handleCopy} aria-label="Copy JSON to clipboard">
          {copied ? (
            <>
              <Check className="w-3.5 h-3.5 mr-1" />
              <span>Copied!</span>
            </>
          ) : (
            <>
              <Copy className="w-3.5 h-3.5 mr-1" />
              <span>Copy</span>
            </>
          )}
        </Button>
      </div>
      {isEditMode ? (
        <>
          <textarea
            value={editText}
            onChange={(e) => {
              setEditText(e.target.value)
              setParseError(null)
            }}
            className="w-full p-4 pt-10 rounded-lg bg-(--color-background-secondary) text-xs font-mono h-[500px] overflow-y-auto border border-(--color-border-default) text-(--color-text-primary) resize-none focus:outline-none focus:ring-2 focus:ring-(--color-accent-primary)"
            spellCheck={false}
            aria-label="Edit JSON configuration"
          />
          {parseError && <p className="mt-1 text-xs text-(--color-semantic-error)">{parseError}</p>}
        </>
      ) : (
        <pre
          className="p-4 pt-10 rounded-lg bg-(--color-background-secondary) text-xs font-mono max-h-[500px] overflow-y-auto overflow-x-auto border border-(--color-border-default)"
          dangerouslySetInnerHTML={{ __html: highlighted }}
        />
      )}
    </div>
  )
})
