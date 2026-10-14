import type { ProjectBinding } from '@/lib/orchestrator-runs/types'

/** One entry of the conversation list: a conversation's own workspace, or a project's shared one. */
export interface Thread {
  projectId: string
  /** The conversation's title (its first message), '새 대화' before one is sent, or the project's own workspace. */
  label: string
  /** When it started, for a conversation; the branch, for a project's own workspace. */
  detail: string
  conversation: boolean
}

export interface ThreadGroup {
  project: string
  threads: Thread[]
}

/** "10월 13일 22:41" in the viewer's time; nothing when the time is unknown. */
export function startedAt(iso: string | null | undefined): string {
  if (!iso) return ''
  const time = new Date(iso)
  if (Number.isNaN(time.getTime())) return ''
  return `${time.getMonth() + 1}월 ${time.getDate()}일 ${String(time.getHours()).padStart(2, '0')}:${String(time.getMinutes()).padStart(2, '0')}`
}

export function threadOf(binding: ProjectBinding): Thread {
  if (binding.conversation) {
    return { projectId: binding.project_id, label: binding.title || '새 대화', detail: startedAt(binding.created_at), conversation: true }
  }
  // A branch someone named (gross-zone-study-20261002) says which workspace this is; the default one says nothing more.
  const named = binding.branch_id !== 'main' && !binding.branch_id.startsWith('c-')
  return { projectId: binding.project_id, label: '프로젝트 작업 공간', detail: named ? binding.branch_id : '', conversation: false }
}

/** The list as a chat app shows it: per project, its conversations newest first, then the project's own workspace. */
export function threadGroups(bindings: readonly ProjectBinding[]): ThreadGroup[] {
  const groups = new Map<string, ProjectBinding[]>()
  for (const binding of bindings) groups.set(binding.owner_project_id, [...(groups.get(binding.owner_project_id) ?? []), binding])
  return [...groups].map(([project, items]) => ({
    project,
    threads: [...items]
      .sort((a, b) => Number(!!b.conversation) - Number(!!a.conversation) || String(b.created_at ?? '').localeCompare(String(a.created_at ?? '')))
      .map(threadOf),
  }))
}
