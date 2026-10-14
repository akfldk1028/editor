import { expect, test } from 'bun:test'
import { historyGroups } from './history'
import type { ProjectBinding } from '@/lib/orchestrator-runs/types'

const binding = (id: string, at: string, title: string): ProjectBinding => ({ project_id: id, owner_project_id: '설계', branch_id: id,
  scene_id: 's', scene_revision: 1, scene_project_id: null, conversation: true, title, updated_at: at })

test('history groups by recent activity, searches titles, and keeps legacy workspaces accessible', () => {
  const items = [binding('old', '2026-10-01T12:00:00', '도서관'), binding('today', '2026-10-14T10:00:00', '어린이집'),
    binding('yesterday', '2026-10-13T12:00:00', '주택'), { ...binding('base', '', ''), conversation: false }]
  const now = new Date('2026-10-14T15:00:00')
  expect(historyGroups(items, '', now).map((group) => group.label)).toEqual(['오늘', '어제', '이전 대화', '프로젝트 작업 공간'])
  expect(historyGroups(items, '어린이집', now).flatMap((group) => group.items).map((item) => item.project_id)).toEqual(['today'])
})
