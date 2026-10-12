'use client'

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { listProjects, type ProjectBinding } from './projects';
import { getRun, listRuns, type RunSummary } from './runs';
import { ProjectConnection } from './ProjectConnection';
import { SpecialistReviewExecution } from './SpecialistReviewExecution';
import { SceneRevisionRefresh } from './SceneRevisionRefresh';
import { currentConversation, restoreConversationProject } from '@/lib/design-conversation/session';

/**
 * 전문가 검토(임시): the specialist-review runner that stays until the design page is folded into /dwg.
 * The run's collaboration record itself is read in the /dwg 협업 artifact (features/artifacts/collaboration).
 */
export default function DialoguePage({ projectId, runId }: { projectId: string; runId: string }) {
  const router = useRouter();
  const [projects, setProjects] = useState<ProjectBinding[]>([]);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [run, setRun] = useState<RunSummary | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    setProjects([]); setRuns([]); setRun(null); setError('');
    async function load() {
      setLoading(true);
      try {
        const nextProjects = await listProjects(controller.signal);
        if (projectId && !nextProjects.some(p => p.project_id === projectId)) throw new Error('연결된 프로젝트를 찾지 못했습니다.');
        if (!projectId) {
          // Nothing chosen yet: the conversation's project (the one /dwg works in), else the only project.
          restoreConversationProject();
          const remembered = currentConversation().projectId;
          const fallback = nextProjects.find(p => p.project_id === remembered) ?? (nextProjects.length === 1 ? nextProjects[0] : undefined);
          if (fallback) { navigate(fallback.project_id); return; }
        }
        const nextRuns = projectId ? await listRuns(projectId, controller.signal) : [];
        if (projectId && !runId && nextRuns.length) { navigate(projectId, nextRuns[0]!.run_id); return; }
        const nextRun = projectId && runId ? await getRun(projectId, runId, controller.signal) : null;
        const binding = nextProjects.find(p => p.project_id === projectId);
        if (nextRun && (nextRun.run_id !== runId || nextRun.owner_project_id !== binding?.owner_project_id || nextRun.branch_id !== binding?.branch_id)) throw new Error('프로젝트와 실행 연결이 일치하지 않습니다.');
        if (controller.signal.aborted) return;
        setProjects(nextProjects); setRuns(nextRuns); setRun(nextRun); setError('');
      } catch (e) {
        if (controller.signal.aborted) return;
        setRun(null); setError(e instanceof Error ? e.message : '대화 기록을 불러오지 못했습니다.');
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
          timer = setTimeout(load, 10_000);
        }
      }
    }
    void load();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [projectId, runId, refresh]);
  function navigate(project: string, selectedRun = '') {
    const query = new URLSearchParams();
    if (project) query.set('project_id', project);
    if (selectedRun) query.set('run_id', selectedRun);
    router.replace(`/dialogue${query.size ? '?' + query : ''}`);
  }
  const selectClass = 'rounded-lg border border-(--color-border-default) bg-(--color-surface-card) p-2 text-(--color-text-primary)';
  const project = projects.find(p => p.project_id === projectId);
  return <div className="space-y-4">
    <h1 className="text-heading-medium text-(--color-text-primary)">전문가 검토 (임시)</h1>
    <p className="text-(--color-text-secondary)">에이전트가 주고받은 대화와 흐름도는 <Link className="underline" href="/dwg?artifact=collaboration">CAD · DWG의 협업 패널</Link>에서 봅니다. 여기에는 전문가 검토 실행만 남아 있어요.</p>
    <ProjectConnection onConnected={p => { navigate(p.project_id); setRefresh(v => v + 1); }} />
    <div className="flex flex-wrap gap-3">
      <label className="text-(--color-text-secondary)">프로젝트 <select aria-label="프로젝트 선택" className={selectClass} value={projectId} onChange={e => navigate(e.target.value)}>
        <option value="">프로젝트 선택</option>
        {projects.map(p => <option key={p.project_id} value={p.project_id}>{p.owner_project_id} · {p.branch_id}</option>)}
      </select></label>
      <label className="text-(--color-text-secondary)">실행 <select aria-label="실행 선택" className={selectClass} value={runId} disabled={!projectId} onChange={e => navigate(projectId, e.target.value)}>
        <option value="">실행 선택</option>
        {runs.map(r => <option key={r.run_id} value={r.run_id}>{r.goal} · {r.status} · {r.run_id}</option>)}
      </select></label>
      <button type="button" className={selectClass} disabled={loading} onClick={() => setRefresh(v => v + 1)}>목록 새로고침</button>
    </div>
    {project && !error && <SceneRevisionRefresh key={`scene:${project.project_id}:${project.scene_revision}`} project={project} onRefreshed={() => setRefresh(v => v + 1)} />}
    {project && !error && <Link className="inline-block underline text-(--color-text-primary)" href={`/scene/${encodeURIComponent(project.scene_id)}`}>현재 프로젝트 3D 장면 열기</Link>}
    {project && !error && <SpecialistReviewExecution key={`review:${project.project_id}:${project.owner_project_id}:${project.branch_id}:${project.scene_id}:${project.scene_revision}`} project={project} followupRun={run} onSubmitted={id => navigate(project.project_id, id)} />}
    {error && <p role="alert" className="text-red-500">{error}</p>}
    {loading && !run && <p role="status">대화 기록을 불러오는 중입니다...</p>}
    {!loading && !error && !run && <p role="status">{projectId && runs.length === 0 ? '이 프로젝트에 저장된 실행이 없습니다.' : '프로젝트와 실행을 선택하면 저장된 요청·응답을 표시합니다.'}</p>}
  </div>;
}
