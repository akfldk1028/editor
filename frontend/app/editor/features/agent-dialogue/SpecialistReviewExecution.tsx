'use client'
import { useEffect, useRef, useState } from 'react'
import { getRunContext } from './runs'
import type { RunSummary } from './runs'
import { FollowupReviewDraft } from './FollowupReviewDraft'
import type { ProjectBinding } from './projects'
import { SpecialistReviewPreview } from './SpecialistReviewPreview'
import {
  parseSpecialistRequest,
  prepareReview,
  readReview,
  saveReview,
  clearReview,
  submitReview,
  ReviewRejected,
  type ReviewAttempt,
  type SpecialistRequest,
} from './specialist-review'

export function SpecialistReviewExecution({
  project,
  onSubmitted,
  followupRun,
}: {
  project: ProjectBinding
  onSubmitted: (runId: string) => void
  followupRun?: RunSummary | null
}) {
  const [request, setRequest] = useState<SpecialistRequest | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [retry, setRetry] = useState(false)
  const [ready, setReady] = useState(false)
  const controller = useRef<AbortController | null>(null)
  const attempt = useRef<ReviewAttempt | null>(null)
  const fileVersion = useRef(0)
  const initialProject = useRef(project)
  useEffect(() => {
    try {
      attempt.current = readReview(sessionStorage, initialProject.current)
      if (attempt.current) {
        setRequest(JSON.parse(attempt.current.body).request)
        setRetry(true)
      }
      setReady(true)
    } catch (e) {
      setError(e instanceof Error ? e.message : '이전 요청 복원 실패')
    }
    return () => {
      controller.current?.abort()
      fileVersion.current++
    }
  }, [])
  async function importFile(file: File | undefined) {
    const version = ++fileVersion.current
    setRequest(null)
    setError('')
    if (!file) return
    try {
      if (file.size > 2 * 1024 * 1024) throw new Error('검토 요청 파일은 2 MB 이하여야 합니다.')
      const value = JSON.parse(await file.text())
      if (version !== fileVersion.current) return
      setRequest(parseSpecialistRequest(value, project))
    } catch (e) {
      if (version === fileVersion.current)
        setError(
          e instanceof SyntaxError
            ? '검토 요청 파일을 JSON으로 읽지 못했습니다.'
            : e instanceof Error
              ? e.message
              : '파일을 읽지 못했습니다.',
        )
    }
  }
  async function submit() {
    if (controller.current || !ready || !request) return
    const active = new AbortController()
    controller.current = active
    setBusy(true)
    setError('')
    try {
      if (!attempt.current) {
        const context = await getRunContext(project.project_id, active.signal)
        if (active.signal.aborted) return
        const prepared = prepareReview(request, context, project)
        saveReview(sessionStorage, project.project_id, prepared)
        attempt.current = prepared
      }
      setRetry(true)
      const runId = await submitReview(project, attempt.current, active.signal)
      if (active.signal.aborted) return
      clearReview(sessionStorage, project.project_id)
      attempt.current = null
      setRetry(false)
      setRequest(null)
      onSubmitted(runId)
    } catch (e) {
      if (active.signal.aborted) return
      if (e instanceof ReviewRejected) {
        clearReview(sessionStorage, project.project_id)
        attempt.current = null
        setRetry(false)
      }
      setError(
        e instanceof Error
          ? e.message
          : '검토 접수 여부를 확인하지 못했습니다. 같은 요청으로 재확인하세요.',
      )
    } finally {
      if (controller.current === active) controller.current = null
      if (!active.signal.aborted) setBusy(false)
    }
  }
  return (
    <section
      aria-label="전문 에이전트 검토"
      className="space-y-3 rounded-lg border border-(--color-border-default) p-4 text-(--color-text-primary)"
    >
      <h2 className="text-heading-small">전문 에이전트 검토</h2>
      {followupRun?.goal === 'specialist_review' && <FollowupReviewDraft
        key={`${project.project_id}:${project.scene_revision}:${followupRun.run_id}`}
        project={project} run={followupRun} disabled={!ready || busy || retry}
        onDraftChanged={() => { fileVersion.current++; setRequest(null) }}
        onPrepared={value => { fileVersion.current++; setRequest(parseSpecialistRequest(value, project)); setError('') }}
      />}
      <p className="text-sm text-(--color-text-secondary)">
        이전 실행의 대화를 이어서 검토 방향을 제안하거나 담당 에이전트의 요청 파일을 가져올 수 있습니다.
        현재 원본 버전을 확인한 뒤 담당 에이전트에게 전달합니다. 제안과 검토 결과는 설계 승인 여부와 구분해 기록됩니다.
      </p>
      <label className="block text-sm">
        담당 에이전트 검토 요청 파일
        <input
          className="block mt-1"
          aria-label="담당 에이전트 검토 요청 파일"
          type="file"
          accept="application/json,.json"
          disabled={!ready || busy || retry}
          onChange={(e) => {
            void importFile(e.target.files?.[0])
            e.target.value = ''
          }}
        />
      </label>
      {request && <SpecialistReviewPreview request={request} project={project} />}
      <button
        type="button"
        disabled={!ready || busy || !request}
        onClick={() => void submit()}
        className="rounded border border-(--color-border-default) p-2 disabled:opacity-50"
      >
        {busy ? '검토 접수 확인 중…' : retry ? '같은 검토 요청 재확인' : '담당 에이전트 검토 실행'}
      </button>
      {retry && (
        <p className="text-sm">
          접수 전 저장한 같은 요청과 식별자로만 재확인합니다. 새로고침해도 이 탭에서 복원됩니다.
        </p>
      )}
      {error && (
        <p role="alert" className="text-red-500">
          {error}
        </p>
      )}
    </section>
  )
}
