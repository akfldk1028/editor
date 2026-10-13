'use client'

import { useEffect, useState } from 'react'
import { listProjects } from '@/lib/orchestrator-runs/api'
import type { ProjectBinding } from '@/lib/orchestrator-runs/types'
import { restoreConversationProject, selectConversationProject, useConversationSelection } from '@/lib/design-conversation/session'

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
      if (!controller.signal.aborted) { setError('프로젝트 목록을 불러오지 못했어요. 새로고침 후 다시 시도해 주세요.'); setLoading(false) }
    })
    return () => controller.abort()
  }, [])
  // A new conversation's workspace is a binding the list has not seen yet: read the list again.
  useEffect(() => {
    if (loading || !selection.projectId || projects.some((project) => project.project_id === selection.projectId)) return
    const controller = new AbortController()
    listProjects(controller.signal).then((items) => { if (!controller.signal.aborted) setProjects(items) }).catch(() => undefined)
    return () => controller.abort()
  }, [selection.projectId, projects, loading])
  const chosen = projects.find((project) => project.project_id === selection.projectId)
  return { ...selection, projectId: chosen?.project_id ?? null, projects, loading, error }
}

export function ConversationProject({ projectId, projects, loading, error }: ReturnType<typeof useConversationProject>) {
  return <div className="conversation-project">
    <label>프로젝트 <select aria-label="대화 프로젝트" value={projectId ?? ''} disabled={loading} onChange={(event) => selectConversationProject(event.target.value || null)}>
      <option value="">{loading ? '불러오는 중…' : '프로젝트 선택'}</option>
      {projects.map((project) => <option key={project.project_id} value={project.project_id}>{project.owner_project_id} · {project.branch_id}</option>)}
    </select></label>
    {error && <p role="alert">{error}</p>}
    {!loading && !error && !projectId && <p>대화를 저장할 프로젝트를 선택해 주세요.</p>}
  </div>
}
