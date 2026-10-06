import { useEffect, useRef } from 'react'
import type { useTeamEditor } from '@/features/team-builder'

type TeamEditor = ReturnType<typeof useTeamEditor>

export function useUndoRedoShortcuts(editor: TeamEditor) {
  // Keyboard shortcuts for undo/redo
  const undoRef = useRef(editor.undo)
  const redoRef = useRef(editor.redo)
  undoRef.current = editor.undo
  redoRef.current = editor.redo

  useEffect(() => {
    if (!editor.isEditing) return
    const handler = (e: KeyboardEvent) => {
      // Don't intercept undo/redo inside text inputs (let native behavior work)
      if (e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLInputElement) return
      if ((e.ctrlKey || e.metaKey) && e.key === 'z' && !e.shiftKey) {
        e.preventDefault()
        undoRef.current()
      }
      if ((e.ctrlKey || e.metaKey) && (e.key === 'y' || (e.key === 'z' && e.shiftKey))) {
        e.preventDefault()
        redoRef.current()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [editor.isEditing])
}
