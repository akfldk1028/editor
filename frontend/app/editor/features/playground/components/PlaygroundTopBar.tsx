import { ExternalLink, History } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Badge } from '@/elements/workspace'
import { ContextUsageRing } from '@/features/context-usage'
import { ExportButton } from '@/features/export'
import { ScheduleIndicator } from '@/features/schedule'
import type { TeamResponse } from '@/features/team-templates/api'
import { getTeamName } from '@/features/team-templates/hooks/useTeams'
import type { useTeamStore } from '@/features/team-templates/model/team-store'
import type { useExecutionStore } from '../executionStore'
import type { filterSessionsByTeam } from '../useExecution'

type ExecutionState = ReturnType<typeof useExecutionStore.getState>

// Format session name for dropdown display
function formatSessionLabel(session: { id?: number; name: string; created_at?: string }): string {
  const date = session.created_at ? new Date(session.created_at).toLocaleDateString() : ''
  const time = session.created_at
    ? new Date(session.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : ''
  const name = session.name || `Session ${session.id ?? '?'}`
  return date ? `${name} (${date} ${time})` : name
}

interface PlaygroundTopBarProps {
  teams: TeamResponse[] | undefined
  selectedTeamId: number | null
  selectedTeam: TeamResponse | undefined
  starting: boolean
  isRunning: ExecutionState['isRunning']
  status: ExecutionState['status']
  turns: ExecutionState['turns']
  currentSessionId: ExecutionState['currentSessionId']
  teamSessions: ReturnType<typeof filterSessionsByTeam>
  sessionsLoading: boolean
  messagesLoading: boolean
  flowPoppedOut: boolean
  rememberSelection: (teamId: number | null, sessionId: number | null, runId?: string) => void
  selectTeam: ReturnType<typeof useTeamStore.getState>['selectTeam']
  handleSessionChange: (value: string) => void
  handlePopOutFlow: () => void
  toggleSchedule: () => void
  totalTokens: number
  percentage: React.ComponentProps<typeof ContextUsageRing>['percentage']
  level: React.ComponentProps<typeof ContextUsageRing>['level']
  displayTotal: React.ComponentProps<typeof ContextUsageRing>['displayTotal']
  displayLimit: React.ComponentProps<typeof ContextUsageRing>['displayLimit']
}

export function PlaygroundTopBar({
  teams,
  selectedTeamId,
  selectedTeam,
  starting,
  isRunning,
  status,
  turns,
  currentSessionId,
  teamSessions,
  sessionsLoading,
  messagesLoading,
  flowPoppedOut,
  rememberSelection,
  selectTeam,
  handleSessionChange,
  handlePopOutFlow,
  toggleSchedule,
  totalTokens,
  percentage,
  level,
  displayTotal,
  displayLimit,
}: PlaygroundTopBarProps) {
  const { t } = useTranslation()
  return (
    <div className="flex items-center gap-3 p-4 border-b border-(--color-border-default) bg-(--color-surface-card) flex-wrap">
      {/* Team selector */}
      <span className="text-label text-(--color-text-secondary)">{t('playground.team')}</span>
      <select
        aria-label="Select a team"
        className="h-9 px-3 rounded-md border border-(--color-border-default) bg-(--color-surface-card) text-sm text-(--color-text-primary)"
        value={selectedTeamId ?? ''}
        disabled={starting || isRunning}
        onChange={(e) => {
          const team = e.target.value ? Number(e.target.value) : null
          rememberSelection(team, null)
          selectTeam(team)
        }}
      >
        <option value="">{t('playground.selectTeam')}</option>
        {teams?.map((t) => (
          <option key={t.id} value={t.id}>
            {getTeamName(t)}
          </option>
        ))}
      </select>

      {/* Separator */}
      <div className="w-px h-6 bg-(--color-border-default)" aria-hidden="true" />

      {/* Session selector */}
      <span className="text-label text-(--color-text-secondary)">
        <History className="w-4 h-4 inline-block mr-1 align-text-bottom" aria-hidden="true" />
        {t('playground.session')}
      </span>
      <select
        aria-label="Select a session"
        className="h-9 px-3 rounded-md border border-(--color-border-default) bg-(--color-surface-card) text-sm text-(--color-text-primary) max-w-[280px]"
        value={currentSessionId ?? 'new'}
        onChange={(e) => handleSessionChange(e.target.value)}
        disabled={!selectedTeamId || isRunning || starting}
      >
        <option value="new">{t('playground.newSession')}</option>
        {teamSessions.map((s) => (
          <option key={s.id} value={s.id}>
            {formatSessionLabel(s)}
          </option>
        ))}
      </select>

      {/* Loading indicator for sessions */}
      {(sessionsLoading || messagesLoading) && (
        <div
          className="w-4 h-4 border-2 border-(--color-accent-primary) border-t-transparent rounded-full animate-spin"
          aria-label="Loading sessions"
        />
      )}

      {/* Status badge */}
      {status !== 'idle' && (
        <Badge
          variant={status === 'running' ? 'success' : status === 'error' ? 'error' : 'default'}
        >
          {status}
        </Badge>
      )}

      {/* Pop Out Flow button */}
      {selectedTeam && !flowPoppedOut && (
        <button
          type="button"
          onClick={handlePopOutFlow}
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs border border-(--color-border-default) hover:bg-(--color-background-secondary) text-(--color-text-secondary) hover:text-(--color-text-primary) transition-colors"
          aria-label="Open flow in new window"
        >
          <ExternalLink className="w-3.5 h-3.5" />
          {t('playground.popOutFlow')}
        </button>
      )}

      {/* Export button */}
      <ExportButton
        turns={turns}
        teamName={selectedTeam ? getTeamName(selectedTeam) : ''}
        disabled={isRunning}
      />

      {/* Schedule indicator */}
      <ScheduleIndicator onClick={toggleSchedule} />

      {/* Context usage ring */}
      {totalTokens > 0 && (
        <ContextUsageRing
          percentage={percentage}
          level={level}
          displayTotal={displayTotal}
          displayLimit={displayLimit}
        />
      )}

      {/* Session indicator */}
      {currentSessionId !== null && (
        <span className="text-body-small text-(--color-text-tertiary) ml-auto">
          Session #{currentSessionId}
        </span>
      )}
    </div>
  )
}
