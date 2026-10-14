import type { ProjectBinding } from '@/lib/orchestrator-runs/types'

export function historyGroups(bindings: readonly ProjectBinding[], query = '', now = new Date()) {
  const midnight = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1).getTime()
  const week = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 7).getTime()
  const groups = ['오늘', '어제', '지난 7일', '이전 대화', '프로젝트 작업 공간'].map((label) => ({ label, items: [] as ProjectBinding[] }))
  const needle = query.trim().toLocaleLowerCase()
  const ordered = [...bindings].sort((a, b) => String(b.updated_at ?? b.created_at ?? '').localeCompare(String(a.updated_at ?? a.created_at ?? '')))
  for (const item of ordered) {
    if (needle && !`${item.title || (item.conversation ? '새 대화' : '프로젝트 작업 공간')} ${item.owner_project_id}`.toLocaleLowerCase().includes(needle)) continue
    const at = Date.parse(item.updated_at ?? item.created_at ?? '')
    const group = !item.conversation ? 4 : at >= midnight ? 0 : at >= yesterday ? 1 : at >= week ? 2 : 3
    groups[group]!.items.push(item)
  }
  return groups.filter((group) => group.items.length)
}
