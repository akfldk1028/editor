'use client'

import { useEffect, useRef, useState } from 'react';
import { refreshSceneRevision, type ProjectBinding } from './projects';

export function SceneRevisionRefresh({ project, onRefreshed }: {
  project: ProjectBinding; onRefreshed: () => void;
}) {
  const [revision, setRevision] = useState<number | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), []);

  async function perform(refresh: boolean) {
    if (pending.current) return;
    const controller = new AbortController();
    pending.current = controller; setBusy(true); setError('');
    try {
      if (refresh && revision !== null) {
        await refreshSceneRevision(project, revision, controller.signal);
        if (!controller.signal.aborted) onRefreshed();
      } else {
        const response = await fetch(`${process.env.NEXT_PUBLIC_BASE_PATH || ''}/api/scenes/${encodeURIComponent(project.scene_id)}`, { signal: controller.signal, cache: 'no-store' });
        if (!response.ok) throw new Error(`장면 확인 실패 (${response.status})`);
        const scene = await response.json();
        if (scene.id !== project.scene_id || scene.projectId !== project.scene_project_id ||
            !Number.isInteger(scene.version) || scene.version < project.scene_revision) {
          throw new Error('저장된 장면의 프로젝트 또는 버전이 연결 정보와 다릅니다.');
        }
        if (!controller.signal.aborted) setRevision(scene.version);
      }
    } catch (e) {
      if (!controller.signal.aborted) {
        setRevision(null);
        setError(e instanceof Error ? e.message : '장면 연결 갱신 실패');
      }
    } finally {
      pending.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  return <section aria-label="장면 버전 연결" className="rounded border border-(--color-border-default) p-3 text-(--color-text-primary)">
    <p>연결된 장면 버전: {project.scene_revision}{revision !== null && ` · 저장된 버전: ${revision}`}</p>
    <p className="my-2 text-sm">장면을 저장한 뒤 연결 버전을 갱신하면 다음 검토는 새 버전을 사용합니다. 기존 실행과 설계 승인 상태는 유지됩니다.</p>
    <button type="button" disabled={busy} className="mr-4 underline" onClick={() => void perform(false)}>저장된 장면 버전 확인</button>
    {revision !== null && revision > project.scene_revision && <button type="button" disabled={busy} className="underline" onClick={() => void perform(true)}>버전 {revision} 연결 갱신</button>}
    {revision === project.scene_revision && <span role="status">현재 저장 버전과 연결되어 있습니다.</span>}
    {error && <p role="alert" className="mt-2 text-red-500">{error}</p>}
  </section>;
}
