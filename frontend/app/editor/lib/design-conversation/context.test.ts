import { afterEach, expect, test } from 'bun:test'
import { conversationSite, setConversationSite } from '@/lib/orchestrator-runs/site-context'
import { activateConversationContext, designConversationContext, rememberConversationLawRun, rememberConversationSite } from './context'
import type { RunLaw } from '@/lib/orchestrator-runs/types'

const result = (pnu: string, runId: string) => ({ run_id: runId, status: 'succeeded', request: { pnu, parcels: [pnu], building_type: null, assessment_date: null }, law: { status: 'succeeded' } as RunLaw })

afterEach(() => activateConversationContext(null))

test('in-flight or failed review is not attached as completed Law evidence', () => {
  rememberConversationSite('unfinished', { pnu: 'site', address: 'site' })
  for (const status of ['running', 'queued', 'failed', 'cancelled']) {
    rememberConversationLawRun('unfinished', 'site', 'run', { ...result('site', 'run'), status })
    expect(designConversationContext('unfinished').law_run_id).toBeUndefined()
  }
  rememberConversationLawRun('unfinished', 'site', 'run', { ...result('site', 'run'), status: 'blocked' })
  expect(designConversationContext('unfinished').law_run_id).toBe('run')
})

test('restored site/date and confirmed Law run feed the selected project conversation', () => {
  activateConversationContext('restored-project')
  rememberConversationSite('restored-project', { pnu: 'site-a', address: '저장된 대지' }, '2026-10-09')
  rememberConversationLawRun('restored-project', 'site-a', 'law-run-a', { ...result('site-a', 'law-run-a'), request: { ...result('site-a', 'law-run-a').request, assessment_date: '2026-10-09' } })
  expect(conversationSite()).toEqual({ pnu: 'site-a', address: '저장된 대지' })
  expect(designConversationContext('restored-project')).toEqual({ pnu: 'site-a', address: '저장된 대지', assessment_date: '2026-10-09', law_run_id: 'law-run-a' })
})

test('project switch cannot inherit another project Law run, even for the same parcel', () => {
  activateConversationContext('project-a')
  rememberConversationSite('project-a', { pnu: 'shared-pnu', address: 'A' })
  rememberConversationLawRun('project-a', 'shared-pnu', 'run-a', result('shared-pnu', 'run-a'))
  activateConversationContext('project-b')
  expect(conversationSite()).toBeNull()
  expect(designConversationContext('project-b')).toEqual({})
  rememberConversationSite('project-b', { pnu: 'shared-pnu', address: 'B' })
  expect(designConversationContext('project-b')).toEqual({ pnu: 'shared-pnu', address: 'B' })
  activateConversationContext('project-a')
  expect(designConversationContext('project-a').law_run_id).toBe('run-a')
})

test('changing parcel excludes the previous Law run and ignores late context from another project', () => {
  activateConversationContext('parcel-project')
  rememberConversationSite('parcel-project', { pnu: 'old-site', address: 'old' })
  rememberConversationLawRun('parcel-project', 'old-site', 'old-run', result('old-site', 'old-run'))
  rememberConversationSite('parcel-project', { pnu: 'new-site', address: 'new' })
  rememberConversationSite('background-project', { pnu: 'other-site', address: 'other' })
  expect(conversationSite()?.pnu).toBe('new-site')
  expect(designConversationContext('parcel-project')).toEqual({ pnu: 'new-site', address: 'new' })
  setConversationSite({ pnu: 'unrelated-site', address: 'unrelated' })
  expect(designConversationContext('parcel-project')).toEqual({ pnu: 'new-site', address: 'new' })
})

test('a mismatched result parcel or run identity never becomes conversation evidence', () => {
  activateConversationContext('checked-project')
  rememberConversationSite('checked-project', { pnu: 'target', address: 'target' })
  rememberConversationLawRun('checked-project', 'target', 'run-a', result('other', 'run-a'))
  rememberConversationLawRun('checked-project', 'target', 'run-b', result('target', 'run-c'))
  expect(designConversationContext('checked-project').law_run_id).toBeUndefined()
})


test('Law evidence must match the selected assessment date', () => {
  rememberConversationSite('dated', { pnu: 'site', address: 'site' }, '2026-10-09')
  const parsed = result('site', 'old-law')
  rememberConversationLawRun('dated', 'site', 'old-law', { ...parsed, request: { ...parsed.request, assessment_date: '2026-10-08' } })
  expect(designConversationContext('dated').law_run_id).toBeUndefined()
  rememberConversationSite('dated', { pnu: 'site', address: 'site' }, '2026-10-08')
  expect(designConversationContext('dated').law_run_id).toBe('old-law')
})
