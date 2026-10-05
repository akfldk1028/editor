import { productPath } from '../../../app/product-path';
import { useEffect, useState } from 'react';
import { createProject, listProjects, type ProjectBinding } from '../api/projects';
import '../agents/agents.css';

export default function ProjectsPage() {
  const [projects, setProjects] = useState<ProjectBinding[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    listProjects(controller.signal).then(items => {if (!controller.signal.aborted) setProjects(items);})
      .catch(reason => {if (!controller.signal.aborted) setError(String(reason.message));})
      .finally(() => {if (!controller.signal.aborted) setLoading(false);});
    return () => controller.abort();
  }, [refresh]);
  return <div className="agent-workspace">
    <h1>프로젝트</h1><p>기존 설계 프로젝트·브랜치와 저장된 3D 장면을 연결합니다.</p>
    <form onSubmit={async event => {
      event.preventDefault();
      const form = event.currentTarget;
      const data = new FormData(form);
      setSaving(true); setError(null);
      try {
        await createProject({owner_project_id:String(data.get('owner_project_id')), branch_id:String(data.get('branch_id')),
          scene_id:String(data.get('scene_id')), scene_revision:Number(data.get('scene_revision')),
          scene_project_id:String(data.get('scene_project_id')).trim() || null});
        form.reset(); setRefresh(value => value + 1);
      } catch (reason) { setError(reason instanceof Error ? reason.message : '연결 실패'); }
      finally {setSaving(false);}
    }}>
      <label>설계 프로젝트 ID <input name="owner_project_id" required maxLength={200} /></label>
      <label>브랜치 ID <input name="branch_id" required maxLength={200} defaultValue="main" /></label>
      <label>장면 ID <input name="scene_id" required maxLength={64} /></label>
      <label>장면의 프로젝트 ID (미지정이면 비움) <input name="scene_project_id" maxLength={200} /></label>
      <label>장면 버전 <input name="scene_revision" required type="number" min="0" step="1" /></label>
      <button disabled={saving} type="submit">{saving ? '확인 중…' : '프로젝트 연결'}</button>
    </form>
    {error && <p role="alert">{error}</p>}
    <button disabled={loading} type="button" onClick={() => setRefresh(value => value + 1)}>목록 새로고침</button>
    {loading ? <p role="status">목록을 불러오는 중…</p> : <ul>{projects.map(project =>
      <li key={project.project_id}><a href={productPath('/projects/' + encodeURIComponent(project.project_id))}>
        {project.owner_project_id} / {project.branch_id}</a></li>)}</ul>}
  </div>;
}
