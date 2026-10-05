'use client'

import { useEffect, useRef, useState, type FormEvent } from 'react';
import { connectProject, type ProjectBinding } from './projects';

export function ProjectConnection({ onConnected }: { onConnected: (project: ProjectBinding) => void }) {
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), []);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending.current) return;
    const data = new FormData(event.currentTarget);
    const controller = new AbortController(); pending.current = controller;
    setBusy(true); setError('');
    try {
      const project = await connectProject({ owner_project_id: String(data.get('owner')).trim(), branch_id: String(data.get('branch')).trim(),
        scene_id: String(data.get('scene')).trim(), scene_revision: Number(data.get('revision')), scene_project_id: String(data.get('sceneProject')).trim() || null }, controller.signal);
      if (!controller.signal.aborted) onConnected(project);
    } catch (e) { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : '프로젝트 연결 실패'); }
    finally { pending.current = null; if (!controller.signal.aborted) setBusy(false); }
  }
  const field = 'rounded border border-(--color-border-default) bg-(--color-surface-card) p-2';
  return <details className="rounded border border-(--color-border-default) p-3 text-(--color-text-primary)">
    <summary>저장된 장면과 에이전트 프로젝트 연결</summary>
    <p className="my-3 text-sm">저장한 Editor 장면과 공유 에이전트 프로젝트를 연결합니다. 프로젝트·브랜치·장면 버전이 실제 원본과 일치해야 합니다.</p>
    <form onSubmit={submit}><fieldset disabled={busy} className="flex flex-wrap items-end gap-3">
      <label className="flex flex-col">에이전트 프로젝트<input className={field} name="owner" required maxLength={200} /></label>
      <label className="flex flex-col">브랜치<input className={field} name="branch" required maxLength={200} /></label>
      <label className="flex flex-col">장면 ID<input className={field} name="scene" required pattern="[A-Za-z0-9_-]+" maxLength={64} /></label>
      <label className="flex flex-col">장면 버전<input className={field} name="revision" type="number" required min={0} step={1} /></label>
      <label className="flex flex-col">장면 프로젝트 ID (선택)<input className={field} name="sceneProject" maxLength={200} /></label>
      <button className={field} type="submit">{busy ? '연결 확인 중…' : '프로젝트 연결'}</button>
    </fieldset></form>
    {error && <p role="alert" className="mt-2 text-red-500">{error}</p>}
  </details>;
}
