'use client'

import { MessageSquare, Search, SquarePen } from 'lucide-react'
import { useState } from 'react'
import { historyGroups } from '@/lib/design-conversation/history'
import { newConversation, selectConversationProject } from '@/lib/design-conversation/session'
import { refreshProjects } from '@/lib/design-conversation/projects'
import { useConversationProject } from '../conversation/ConversationProject'

export function ConversationSidebar({ compact = false, onSelected }: { compact?: boolean; onSelected(): void }) {
  const { projects, projectId, loading, error } = useConversationProject()
  const [query, setQuery] = useState('')
  const [creating, setCreating] = useState(false)
  const [failure, setFailure] = useState<string | null>(null)
  const groups = historyGroups(projects, query)
  const chosen = projects.find((item) => item.project_id === projectId)
  const owners = [...new Set(projects.map((item) => item.owner_project_id))]
  const start = async () => {
    if (creating || !projectId) return
    setCreating(true)
    setFailure(null)
    try { if (await newConversation()) { setQuery(''); onSelected() } }
    catch { setFailure('새 대화를 만들지 못했어요. 다시 시도해 주세요.') }
    finally { setCreating(false) }
  }
  if (compact) return <button aria-label="새 대화" className="icon-button" disabled={loading || creating || !projectId}
    title={failure ?? '새 대화'} onClick={() => void start()} type="button"><SquarePen size={17} /></button>
  return <section aria-label="대화 목록" className="conversation-sidebar">
    <button className="sidebar-new-chat" disabled={loading || creating || !projectId} onClick={() => void start()} type="button">
      <SquarePen aria-hidden="true" size={17} /><span>{creating ? '대화 만드는 중…' : '새 대화'}</span>
    </button>
    {owners.length > 1 && <label className="conversation-project-choice"><span>프로젝트</span>
      <select aria-label="새 대화 프로젝트" value={chosen?.owner_project_id ?? ''} onChange={(event) => {
        const candidates = projects.filter((item) => item.owner_project_id === event.target.value)
        const next = candidates.find((item) => !item.conversation) ?? candidates[0]
        if (next) { selectConversationProject(next.project_id); onSelected() }
      }}>{!chosen && <option value="">선택하세요</option>}{owners.map((owner) => <option key={owner} value={owner}>{owner}</option>)}</select>
    </label>}
    <label className="conversation-search"><Search aria-hidden="true" size={15} />
      <input aria-label="대화 검색" placeholder="대화 검색" type="search" value={query} onChange={(event) => setQuery(event.target.value)} />
    </label>
    {(error || failure) && <p className="sidebar-notice" role="alert">{failure ?? '대화 목록을 불러오지 못했어요.'}
      {error && <button onClick={() => void refreshProjects().catch(() => undefined)} type="button">다시 불러오기</button>}
    </p>}
    <nav aria-label="저장된 대화" className="conversation-history">
      {loading ? <p className="sidebar-notice" role="status">대화를 불러오는 중…</p> : groups.map((group) => <section key={group.label}>
        <h2>{group.label}</h2>
        {group.items.map((item) => <button aria-current={item.project_id === projectId ? 'page' : undefined} className="history-entry"
          key={item.project_id} title={item.title || item.owner_project_id} type="button" onClick={() => {
            selectConversationProject(item.project_id); setFailure(null); onSelected()
          }}><MessageSquare aria-hidden="true" size={14} /><span>{item.title || (item.conversation ? '새 대화' : item.owner_project_id)}
            </span></button>)}
      </section>)}
      {!loading && !groups.length && <p className="sidebar-notice">{query ? '검색한 대화가 없어요.' : '아직 대화가 없어요. 프로젝트를 연결하면 새 대화를 시작할 수 있어요.'}</p>}
    </nav>
  </section>
}
