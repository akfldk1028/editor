'use client'
import { Button, Card } from '@/elements/workspace'
import type { PatternType } from '@/features/team-builder'
import {
  AgentAddDialog,
  AgentConfigPanel,
  EditableAgentPanel,
  JsonView,
  PATTERN_LABELS,
  PatternSelector,
  TerminationEditor,
  useTeamEditor,
} from '@/features/team-builder'
import type { TeamResponse } from '@/features/team-templates/api'
import { validationAPI } from '@/features/team-templates/api'
import type {
  AgentConfig,
  Component,
  ComponentConfig,
  TeamConfig,
  TerminationConfig,
} from '@/lib/contracts/workspace'
import { truncateError } from '@/lib/display-error'
import { assertTeamShape } from '@/features/team-builder/model/component-shape'
import { PointerSensor, useSensor, useSensors, type DragEndEvent } from '@dnd-kit/core'
import { Plus } from 'lucide-react'
import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from 'react'
import { TeamCreateDialog, TeamDeleteDialog } from './components'
import { TeamAgentChips } from './TeamAgentChips'
import { TeamPanelHeader } from './TeamPanelHeader'
import { TeamCard } from './components/TeamCard'
import { UnsavedChangesDialog } from './components/UnsavedChangesDialog'
import { getTeamName, getTeamPattern, useTeams } from './hooks/useTeams'
import { useUnsavedChanges } from './hooks/useUnsavedChanges'
import { downloadJSON, getParticipants, getTermination } from './model/presentation'
import { useUndoRedoShortcuts } from './useUndoRedoShortcuts'

// Lazy-load AgentFlow (pulls in @xyflow/react + d3 + dagre ~270KB)
const AgentFlow = lazy(() =>
  import('@/features/team-builder/agentflow').then((m) => ({ default: m.AgentFlow })),
)

export function TeamsPage() {
  const { data: teams, isLoading, error } = useTeams()
  const [selectedTeamId, setSelectedTeamId] = useState<number | null>(null)
  const [selectedNodeLabel, setSelectedNodeLabel] = useState<string | null>(null)
  const [showJson, setShowJson] = useState(false)
  const [showPatterns, setShowPatterns] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<TeamResponse | null>(null)
  const [addAgentOpen, setAddAgentOpen] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  const editor = useTeamEditor()
  const [pendingAction, setPendingAction] = useState<(() => void) | null>(null)
  const requestAction = useCallback(
    (action: () => void) => {
      if (editor.isDirty) setPendingAction(() => action)
      else action()
    },
    [editor.isDirty],
  )

  // DnD sensors with distance constraint to distinguish click from drag
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 8 } }))

  useUndoRedoShortcuts(editor)

  // Block navigation when there are unsaved edits
  const blocker = useUnsavedChanges(editor.isEditing && editor.isDirty)

  // Also block browser close/refresh with unsaved edits
  useEffect(() => {
    if (!editor.isEditing || !editor.isDirty) return
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault()
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [editor.isEditing, editor.isDirty])

  const selectedTeam = teams?.find((t) => t.id === selectedTeamId)

  // Use draft participants when editing, real participants otherwise
  const selectedParticipants = useMemo(() => {
    if (editor.isEditing && editor.draft?.teamId === selectedTeamId) {
      return editor.participants
    }
    return selectedTeam ? getParticipants(selectedTeam) : []
  }, [editor.isEditing, editor.draft, editor.participants, selectedTeamId, selectedTeam])

  const draftTermination = useMemo(() => {
    if (editor.isEditing && editor.draft?.teamId === selectedTeamId) {
      const config = editor.draft.component.config as unknown as Record<string, unknown>
      return config?.termination_condition as Component<TerminationConfig> | undefined
    }
    return selectedTeam ? getTermination(selectedTeam) : undefined
  }, [editor.isEditing, editor.draft, selectedTeamId, selectedTeam])

  const selectedPattern = useMemo(() => {
    if (editor.isEditing && editor.draft?.teamId === selectedTeamId) {
      return getTeamPattern({
        id: editor.draft.teamId,
        component: editor.draft.component,
      } as TeamResponse)
    }
    return selectedTeam ? getTeamPattern(selectedTeam) : 'unknown'
  }, [editor.isEditing, editor.draft, selectedTeamId, selectedTeam])

  const selectedName = selectedTeam ? getTeamName(selectedTeam) : ''
  const patternInfo =
    PATTERN_LABELS[selectedPattern as keyof typeof PATTERN_LABELS] ?? PATTERN_LABELS.unknown

  const flowParticipants = useMemo(
    () =>
      selectedParticipants.map((p) => ({
        config: { name: p.config?.name },
        label: p.label ?? '',
        description: p.description ?? '',
      })),
    [selectedParticipants],
  )

  const selectedAgent = useMemo(() => {
    if (!selectedNodeLabel || !selectedParticipants.length) return null
    return (
      selectedParticipants.find((p) => (p.label ?? p.config?.name ?? '') === selectedNodeLabel) ??
      null
    )
  }, [selectedNodeLabel, selectedParticipants])

  const selectedAgentIndex = useMemo(() => {
    if (!selectedNodeLabel || !selectedParticipants.length) return -1
    return selectedParticipants.findIndex(
      (p) => (p.label ?? p.config?.name ?? '') === selectedNodeLabel,
    )
  }, [selectedNodeLabel, selectedParticipants])

  // DnD sortable chip IDs (name-based for stable React keys across reorder)
  const chipIds = useMemo(
    () => selectedParticipants.map((p, i) => p.label ?? p.config?.name ?? `agent-${i}`),
    [selectedParticipants],
  )

  const handleNodeClick = useCallback((label: string) => {
    setSelectedNodeLabel((prev) => (prev === label ? null : label))
    setShowJson(false)
  }, [])

  const handleCloseConfigPanel = useCallback(() => {
    setSelectedNodeLabel(null)
  }, [])

  const handleClosePanel = useCallback(
    () =>
      requestAction(() => {
        if (editor.isEditing) editor.cancelEditing()
        setSelectedTeamId(null)
        setSelectedNodeLabel(null)
        setShowJson(false)
        setShowPatterns(false)
      }),
    [editor, requestAction],
  )

  const handleSelectTeam = useCallback(
    (teamId: number) =>
      requestAction(() => {
        if (editor.isEditing) editor.cancelEditing()
        setSelectedTeamId((prev) => (prev === teamId ? null : teamId))
        setSelectedNodeLabel(null)
        setShowJson(false)
        setShowPatterns(false)
      }),
    [editor, requestAction],
  )

  const handleOpenCreate = useCallback(() => setCreateOpen(true), [])
  const handleCloseCreate = useCallback(() => setCreateOpen(false), [])

  const handleDeleteTeam = useCallback((team: TeamResponse) => {
    setDeleteTarget(team)
  }, [])

  const handleCloseDelete = useCallback(() => setDeleteTarget(null), [])
  const handleDeleted = useCallback(
    (deletedId: number) => {
      setDeleteTarget(null)
      if (deletedId === selectedTeamId) {
        editor.cancelEditing()
        setSelectedTeamId(null)
        setSelectedNodeLabel(null)
      }
    },
    [editor, selectedTeamId],
  )

  const handleToggleEdit = useCallback(() => {
    if (editor.isEditing) {
      requestAction(editor.cancelEditing)
    } else if (selectedTeam) {
      editor.startEditing(selectedTeam)
    }
  }, [editor, selectedTeam, requestAction])

  const handleSave = useCallback(async () => {
    try {
      setSaveError(null)
      // Validate before saving
      if (editor.draft?.component) {
        try {
          const validation = await validationAPI.validate(
            editor.draft.component as unknown as Component<ComponentConfig>,
          )
          if (!validation.is_valid) {
            setSaveError(`Validation failed: ${validation.errors.map((e) => e.error).join(', ')}`)
            return
          }
        } catch {
          // If validation API is unavailable, proceed with save anyway
        }
      }
      await editor.save()
    } catch (e) {
      setSaveError(truncateError(e instanceof Error ? e.message : 'Failed to save team'))
    }
  }, [editor])

  const handlePatternSelect = useCallback(
    (pattern: PatternType) => {
      if (editor.isEditing) {
        editor.updatePattern(pattern)
      }
    },
    [editor],
  )

  const handleAddAgent = useCallback(
    (agent: Component<AgentConfig>) => {
      editor.addParticipant(agent)
    },
    [editor],
  )

  const handleOpenAddAgent = useCallback(() => setAddAgentOpen(true), [])
  const handleCloseAddAgent = useCallback(() => setAddAgentOpen(false), [])
  const handleDiscard = useCallback(() => editor.cancelEditing(), [editor])
  const handleTogglePatterns = useCallback(() => setShowPatterns((p) => !p), [])
  const handleToggleJson = useCallback(() => {
    setShowJson((j) => !j)
    setSelectedNodeLabel(null)
  }, [])

  const handleExport = useCallback(() => {
    downloadJSON(
      editor.isEditing ? editor.draft?.component : selectedTeam?.component,
      `${selectedName.replace(/\s+/g, '_').toLowerCase()}.json`,
    )
  }, [editor.isEditing, editor.draft, selectedTeam, selectedName])

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      const { active, over } = event
      if (over && active.id !== over.id) {
        const fromIndex = chipIds.indexOf(String(active.id))
        const toIndex = chipIds.indexOf(String(over.id))
        if (fromIndex >= 0 && toIndex >= 0) {
          editor.reorderParticipants(fromIndex, toIndex)
        }
      }
    },
    [editor, chipIds],
  )

  const handleJsonChange = useCallback(
    (data: unknown) => {
      assertTeamShape(data)
      setSaveError(null)
      editor.updateDraftComponent(data as Component<TeamConfig>)
    },
    [editor],
  )

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-display-medium">Team Builder</h1>
          <p className="text-body-medium text-(--color-text-secondary) mt-1">
            Build and manage agent teams
          </p>
        </div>
        <Button onClick={handleOpenCreate}>
          <Plus className="w-4 h-4 mr-2" />
          New Team
        </Button>
      </div>

      {/* Agent Flow Graph Panel */}
      {selectedTeam && (
        <Card className="relative">
          <TeamPanelHeader
            editor={editor}
            selectedTeam={selectedTeam}
            selectedName={selectedName}
            selectedPattern={selectedPattern}
            patternInfo={patternInfo}
            showPatterns={showPatterns}
            showJson={showJson}
            handleOpenAddAgent={handleOpenAddAgent}
            handleSave={handleSave}
            handleDiscard={handleDiscard}
            handleToggleEdit={handleToggleEdit}
            handleExport={handleExport}
            handleTogglePatterns={handleTogglePatterns}
            handleToggleJson={handleToggleJson}
            handleClosePanel={handleClosePanel}
          />

          {/* Pattern Selector (toggle) - interactive in edit mode */}
          {showPatterns && (
            <PatternSelector
              currentPattern={selectedPattern as PatternType}
              onSelect={editor.isEditing ? handlePatternSelect : undefined}
            />
          )}

          {/* Save error message */}
          {saveError && <p className="text-sm text-(--color-semantic-error) mb-3">{saveError}</p>}

          {/* Termination Editor (edit mode only) */}
          {editor.isEditing && (
            <div className="mb-3">
              <TerminationEditor value={draftTermination} onChange={editor.updateTermination} />
            </div>
          )}

          {/* JSON vs Graph toggle */}
          {showJson ? (
            <JsonView
              data={editor.isEditing ? editor.draft?.component : selectedTeam.component}
              editable={editor.isEditing}
              onChange={handleJsonChange}
            />
          ) : (
            <div className="flex gap-4">
              <div className={selectedAgent ? 'flex-1 min-w-0' : 'w-full'}>
                <Suspense
                  fallback={
                    <div className="flex items-center justify-center h-[400px]">
                      <div className="w-6 h-6 border-2 border-(--color-accent-primary) border-t-transparent rounded-full animate-spin" />
                    </div>
                  }
                >
                  <AgentFlow
                    teamProvider={
                      editor.isEditing
                        ? editor.draft?.component.provider
                        : selectedTeam.component?.provider
                    }
                    participants={flowParticipants}
                    height={400}
                    onNodeClick={handleNodeClick}
                  />
                </Suspense>
              </div>
              {selectedAgent && (
                <div className="w-80 flex-shrink-0">
                  {editor.isEditing && selectedAgentIndex >= 0 ? (
                    <EditableAgentPanel
                      agent={selectedAgent}
                      index={selectedAgentIndex}
                      onUpdate={editor.updateParticipant}
                      onRemove={editor.removeParticipant}
                      onClose={handleCloseConfigPanel}
                    />
                  ) : (
                    <AgentConfigPanel agent={selectedAgent} onClose={handleCloseConfigPanel} />
                  )}
                </div>
              )}
            </div>
          )}

          {/* Agent chips - sortable via DnD in edit mode */}
          <TeamAgentChips
            isEditing={editor.isEditing}
            sensors={sensors}
            handleDragEnd={handleDragEnd}
            chipIds={chipIds}
            selectedParticipants={selectedParticipants}
            selectedNodeLabel={selectedNodeLabel}
            handleNodeClick={handleNodeClick}
          />
        </Card>
      )}

      {error && (
        <p role="alert" className="text-(--color-semantic-error)">
          {error.message}
        </p>
      )}
      {isLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[1, 2, 3].map((i) => (
            <Card key={i} className="animate-pulse">
              <div className="h-4 bg-(--color-background-secondary) rounded w-3/4" />
              <div className="h-3 bg-(--color-background-secondary) rounded w-1/2 mt-3" />
              <div className="h-8 bg-(--color-background-secondary) rounded w-20 mt-4" />
            </Card>
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {teams?.map((team) => (
            <TeamCard
              key={team.id}
              team={team}
              isSelected={team.id === selectedTeamId}
              onSelect={() => handleSelectTeam(team.id)}
              onDelete={() => handleDeleteTeam(team)}
            />
          ))}
          {!error && (!teams || teams.length === 0) && (
            <Card className="col-span-full text-center py-12">
              <p className="text-body-large text-(--color-text-secondary)">
                No teams found. Create your first team or import a saved gallery template.
              </p>
              <Button className="mt-4" onClick={handleOpenCreate}>
                <Plus className="w-4 h-4 mr-2" />
                Create Team
              </Button>
            </Card>
          )}
        </div>
      )}

      {/* Dialogs */}
      <TeamCreateDialog open={createOpen} onClose={handleCloseCreate} />
      <TeamDeleteDialog team={deleteTarget} onClose={handleCloseDelete} onDeleted={handleDeleted} />
      <AgentAddDialog open={addAgentOpen} onClose={handleCloseAddAgent} onAdd={handleAddAgent} />

      {/* Unsaved changes navigation blocker */}
      {(blocker.state === 'blocked' || pendingAction) && (
        <UnsavedChangesDialog
          onStay={() => {
            setPendingAction(null)
            blocker.reset()
          }}
          onLeave={() => {
            if (pendingAction) {
              pendingAction()
              setPendingAction(null)
            } else {
              editor.cancelEditing()
              blocker.proceed()
            }
          }}
        />
      )}
    </div>
  )
}
