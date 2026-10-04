import { useEffect, useState } from 'react';
import { getProject, type ProjectBinding } from '../api/projects';
import '../agents/agents.css';
import {TaskComposer} from '../runs/TaskComposer';
import {RunList} from '../runs/RunList';
import {SavedDesigns} from './SavedDesigns';
import {SavedExecutions} from './SavedExecutions';
import {NativeDesignJobs} from './NativeDesignJobs';

export default function ProjectPage({projectId}: {projectId: string}) {
  const [project, setProject] = useState<ProjectBinding | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refresh,setRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setProject(null); setError(null);
    getProject(projectId, controller.signal).then(value => {if (!controller.signal.aborted) setProject(value);})
      .catch(reason => {if (!controller.signal.aborted) setError(String(reason.message));});
    return () => controller.abort();
  }, [projectId]);
  return <div className="agent-workspace"><a href="/projects">프로젝트 목록</a>
    {error ? <p role="alert">{error}</p> : !project ? <p role="status">불러오는 중…</p> : <>
      <h1>{project.owner_project_id}</h1><p>브랜치: {project.branch_id}</p>
      <p>연결된 장면: {project.scene_id} · 기준 버전 {project.scene_revision}</p>
      <a href={'/editor/scene/' + encodeURIComponent(project.scene_id)}>3D 장면 열기</a>
      <NativeDesignJobs key={project.project_id} project={project} />
      <SavedDesigns key={project.project_id} project={project} />
      <SavedExecutions key={project.project_id} project={project} />
      <TaskComposer key={project.project_id} projectId={project.project_id} onSubmitted={() => setRefresh(value=>value+1)} />
      <RunList projectId={project.project_id} refresh={refresh} />
    </>}
  </div>;
}
