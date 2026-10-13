import { expect, test } from 'bun:test'
import type { ProjectBinding } from '@/lib/orchestrator-runs/types'
import { startedAt, threadGroups } from './threads'

const binding = (over: Partial<ProjectBinding>): ProjectBinding => ({
  project_id: 'p', owner_project_id: 'gosan', branch_id: 'main', scene_id: 's', scene_revision: 1, scene_project_id: null, ...over })

test('the list shows conversations by title, newest first, per project, and the project workspace last', () => {
  const groups = threadGroups([
    binding({ project_id: 'base' }),
    binding({ project_id: 'old', branch_id: 'c-1', conversation: true, title: '684-1 건폐율', created_at: '2026-10-13T12:00:00Z' }),
    binding({ project_id: 'new', branch_id: 'c-2', conversation: true, title: null, created_at: '2026-10-13T13:00:00Z' }),
    binding({ project_id: 'other', owner_project_id: 'r39' }),
  ])
  expect(groups.map((group) => group.project)).toEqual(['gosan', 'r39'])
  expect(groups[0]!.threads.map((thread) => [thread.projectId, thread.label])).toEqual([
    ['new', '새 대화'], ['old', '684-1 건폐율'], ['base', '프로젝트 작업 공간']])
  expect(groups[0]!.threads[2]!.detail).toBe('main')
})

test('a start time reads as month, day and time; an unknown one as nothing', () => {
  expect(startedAt('2026-10-13T13:05:00')).toBe('10월 13일 13:05')
  expect(startedAt(null)).toBe('')
  expect(startedAt('not a time')).toBe('')
})
