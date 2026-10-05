export interface ProjectBinding {
  project_id: string;
  owner_project_id: string;
  branch_id: string;
  scene_id: string;
  scene_revision: number;
  scene_project_id: string | null;
}

function parseBinding(value: unknown): ProjectBinding {
  const item = value as ProjectBinding | null;
  if (!item || !['project_id','owner_project_id','branch_id','scene_id'].every(
    key => typeof item[key as keyof ProjectBinding] === 'string') ||
    !Number.isInteger(item.scene_revision) || item.scene_revision < 0 ||
    (item.scene_project_id !== null && typeof item.scene_project_id !== 'string')) {
    throw new Error('프로젝트 응답 형식이 올바르지 않습니다.');
  }
  return item;
}

async function request(path: string, options?: RequestInit): Promise<unknown> {
  const response = await fetch((process.env.NEXT_PUBLIC_BASE_PATH || '') + '/api/v1/platform/projects' + path, options);
  if (!response.ok) throw new Error(`프로젝트 연결 실패 (${response.status})`);
  return response.json();
}

export async function listProjects(signal?: AbortSignal): Promise<ProjectBinding[]> {
  const data = await request('', {signal});
  if (!Array.isArray(data)) throw new Error('프로젝트 목록 형식이 올바르지 않습니다.');
  return data.map(parseBinding);
}

export async function connectProject(input: Omit<ProjectBinding, 'project_id'>, signal?: AbortSignal): Promise<ProjectBinding> {
  return parseBinding(await request('', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input), signal }));
}
