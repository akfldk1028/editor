import { Code, Download, Eye, Pencil, Redo2, Save, Target, Undo2, UserPlus, X } from 'lucide-react'
import { Badge, Button } from '@/elements/workspace'
import type { PATTERN_LABELS, useTeamEditor } from '@/features/team-builder'
import type { TeamResponse } from '@/features/team-templates/api'
import { PATTERN_COLORS } from '../model/presentation'
import { ValidationBadge } from './ValidationBadge'

type TeamEditor = ReturnType<typeof useTeamEditor>

interface TeamPanelHeaderProps {
  editor: TeamEditor
  selectedTeam: TeamResponse
  selectedName: string
  selectedPattern: string
  patternInfo: (typeof PATTERN_LABELS)[keyof typeof PATTERN_LABELS]
  showPatterns: boolean
  showJson: boolean
  handleOpenAddAgent: () => void
  handleSave: () => void
  handleDiscard: () => void
  handleToggleEdit: () => void
  handleExport: () => void
  handleTogglePatterns: () => void
  handleToggleJson: () => void
  handleClosePanel: () => void
}

export function TeamPanelHeader({
  editor,
  selectedTeam,
  selectedName,
  selectedPattern,
  patternInfo,
  showPatterns,
  showJson,
  handleOpenAddAgent,
  handleSave,
  handleDiscard,
  handleToggleEdit,
  handleExport,
  handleTogglePatterns,
  handleToggleJson,
  handleClosePanel,
}: TeamPanelHeaderProps) {
  return (
    <div className="flex items-center justify-between mb-3">
      <div className="flex items-center gap-3">
        <h2 className="text-heading-small">{selectedName}</h2>
        <Badge variant={PATTERN_COLORS[selectedPattern] ?? 'default'}>{patternInfo.label}</Badge>
        <span className="text-body-small text-(--color-text-tertiary)">
          {patternInfo.description}
        </span>
        <ValidationBadge
          component={editor.isEditing ? editor.draft?.component : selectedTeam.component}
        />
        {editor.isEditing && <Badge variant="warning">Editing</Badge>}
      </div>
      <div className="flex items-center gap-2">
        {/* Edit mode toolbar */}
        {editor.isEditing && (
          <>
            <Button
              size="sm"
              variant="ghost"
              onClick={editor.undo}
              disabled={!editor.canUndo}
              aria-label="Undo"
              title="Undo (Ctrl+Z)"
            >
              <Undo2 className="w-3.5 h-3.5" />
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={editor.redo}
              disabled={!editor.canRedo}
              aria-label="Redo"
              title="Redo (Ctrl+Y)"
            >
              <Redo2 className="w-3.5 h-3.5" />
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={handleOpenAddAgent}
              aria-label="Add agent to team"
            >
              <UserPlus className="w-3.5 h-3.5 mr-1.5" />
              Add Agent
            </Button>
            <Button
              size="sm"
              variant="primary"
              onClick={handleSave}
              disabled={!editor.isDirty || editor.isSaving}
              aria-label="Save team changes"
            >
              <Save className="w-3.5 h-3.5 mr-1.5" />
              {editor.isSaving ? 'Saving...' : 'Save'}
            </Button>
            <Button size="sm" variant="ghost" onClick={handleDiscard} aria-label="Discard changes">
              <X className="w-3.5 h-3.5 mr-1.5" />
              Discard
            </Button>
          </>
        )}
        <Button
          size="sm"
          variant={editor.isEditing ? 'primary' : 'ghost'}
          onClick={handleToggleEdit}
          aria-label={editor.isEditing ? 'Exit edit mode' : 'Enter edit mode'}
        >
          <Pencil className="w-3.5 h-3.5 mr-1.5" />
          Edit
        </Button>
        <Button size="sm" variant="ghost" onClick={handleExport} aria-label="Download team as JSON">
          <Download className="w-3.5 h-3.5 mr-1.5" />
          Export
        </Button>
        <Button
          size="sm"
          variant={showPatterns ? 'primary' : 'ghost'}
          onClick={handleTogglePatterns}
          aria-label="Toggle pattern selector"
        >
          <Target className="w-3.5 h-3.5 mr-1.5" />
          Patterns
        </Button>
        <Button
          size="sm"
          variant={showJson ? 'primary' : 'ghost'}
          onClick={handleToggleJson}
          aria-label={showJson ? 'Show graph view' : 'Show JSON view'}
        >
          {showJson ? (
            <>
              <Eye className="w-3.5 h-3.5 mr-1.5" />
              Graph
            </>
          ) : (
            <>
              <Code className="w-3.5 h-3.5 mr-1.5" />
              JSON
            </>
          )}
        </Button>
        <button
          onClick={handleClosePanel}
          className="p-1 rounded hover:bg-(--color-background-secondary) text-(--color-text-tertiary) focus:outline-none focus:ring-2 focus:ring-(--color-accent-primary)"
          aria-label="Close graph panel"
        >
          <X className="w-4 h-4" />
        </button>
      </div>
    </div>
  )
}
