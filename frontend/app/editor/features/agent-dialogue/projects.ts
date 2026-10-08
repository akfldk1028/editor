import { listProjects, parseBinding } from '@/lib/orchestrator-runs/api'
import type { ProjectBinding } from '@/lib/orchestrator-runs/types'

export { listProjects }
export type { ProjectBinding }

async function request(path: string, options?: RequestInit): Promise<unknown> {
  const response = await fetch((process.env.NEXT_PUBLIC_BASE_PATH || '') + '/api/v1/platform/projects' + path, options);
  if (!response.ok) throw new Error(`프로젝트 연결 실패 (${response.status})`);
  return response.json();
}

export async function connectProject(input: Omit<ProjectBinding, 'project_id'>, signal?: AbortSignal): Promise<ProjectBinding> {
  return parseBinding(await request('', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input), signal }));
}

export async function refreshSceneRevision(project: ProjectBinding, revision: number, signal?: AbortSignal): Promise<ProjectBinding> {
  const result = parseBinding(await request(`/${encodeURIComponent(project.project_id)}/scene-revision`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, signal,
    body: JSON.stringify({ expected_scene_revision: project.scene_revision, scene_revision: revision }),
  }));
  if (result.project_id !== project.project_id || result.scene_id !== project.scene_id ||
      result.owner_project_id !== project.owner_project_id || result.branch_id !== project.branch_id ||
      result.scene_project_id !== project.scene_project_id || result.scene_revision !== revision) {
    throw new Error('Scene binding response does not match this project.');
  }
  return result;
}
