'use client'

import { Check, ChevronDown, MessagesSquare } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { listProjects } from '@/lib/orchestrator-runs/api'
import type { ProjectBinding } from '@/lib/orchestrator-runs/types'
import { restoreConversationProject, selectConversationProject, useConversationSelection } from '@/lib/design-conversation/session'
import { threadGroups, threadOf } from '@/lib/design-conversation/threads'
import { feedForProject, useFeed } from '@/lib/orchestrator-runs/feed'

export function useConversationProject() {
  const selection = useConversationSelection()
  const [projects, setProjects] = useState<ProjectBinding[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    restoreConversationProject()
    const controller = new AbortController()
    listProjects(controller.signal).then((items) => {
      if (!controller.signal.aborted) { setProjects(items); setLoading(false) }
    }).catch(() => {
      if (!controller.signal.aborted) { setError('대화 목록을 불러오지 못했어요. 새로고침 후 다시 시도해 주세요.'); setLoading(false) }
    })
    return () => controller.abort()
  }, [])
  // A new conversation's workspace is a binding the list has not seen yet, and its title comes with its first
  // message: read the list again when the selection changes, and when this conversation gains a message while untitled.
  const said = feedForProject(useFeed(), selection.projectId, selection.conversationId).length
  // biome-ignore lint/correctness/useExhaustiveDependencies: `projects` is what this effect refreshes; reading it again on its own update would loop.
  useEffect(() => {
    if (loading || !selection.projectId) return
    const chosen = projects.find((project) => project.project_id === selection.projectId)
    if (chosen && !(chosen.conversation && !chosen.title && said > 0)) return
    const controller = new AbortController()
    listProjects(controller.signal).then((items) => { if (!controller.signal.aborted) setProjects(items) }).catch(() => undefined)
    return () => controller.abort()
  }, [selection.projectId, said, loading])
  const chosen = projects.find((project) => project.project_id === selection.projectId)
  return { ...selection, projectId: chosen?.project_id ?? null, projects, loading, error }
}

/**
 * The conversation list, as a chat app keeps it: the current conversation by its title, and on opening every
 * conversation per project, newest first, with the project's own shared workspace last.
 */
export function ConversationProject({ projectId, projects, loading, error }: ReturnType<typeof useConversationProject>) {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const close = (event: MouseEvent) => { if (box.current && !box.current.contains(event.target as Node)) setOpen(false) }
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', onKey) }
  }, [open])
  const chosen = projects.find((project) => project.project_id === projectId)
  const current = chosen ? threadOf(chosen) : null
  const pick = (id: string) => { setOpen(false); selectConversationProject(id) }
  return <div className="conversation-project" ref={box}>
    <button aria-expanded={open} aria-haspopup="listbox" aria-label="대화 목록" className="conversation-current" disabled={loading} onClick={() => setOpen((value) => !value)} type="button">
      <MessagesSquare aria-hidden="true" size={14} />
      <span>{loading ? '불러오는 중…' : current ? current.label : '대화를 고르세요'}</span>
      {chosen && <small>{chosen.owner_project_id}</small>}
      <ChevronDown aria-hidden="true" size={14} />
    </button>
    {open && (
      <div className="conversation-threads" role="listbox" aria-label="대화">
        {threadGroups(projects).map((group) => (
          <section key={group.project}>
            <h4>{group.project}</h4>
            {group.threads.map((thread) => (
              <button aria-selected={thread.projectId === projectId} className="conversation-thread" data-conversation={thread.conversation ? 'true' : 'false'}
                key={thread.projectId} onClick={() => pick(thread.projectId)} role="option" type="button">
                <span>{thread.label}</span>
                {thread.detail && <small>{thread.detail}</small>}
                {thread.projectId === projectId && <Check aria-hidden="true" size={13} />}
              </button>
            ))}
          </section>
        ))}
      </div>
    )}
    {error && <p role="alert">{error}</p>}
    {!loading && !error && !projectId && <p>대화를 고르거나 위의 새 대화 버튼을 눌러 주세요.</p>}
  </div>
}
