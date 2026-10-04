export interface NativeDesignSummary {
  job_id: string;
  project_id: string;
  request_id: string;
  status: 'created';
  execution_supported: false;
  created_at: string;
  site_area_m2: number;
  algorithm: string;
  building_type: string;
  max_generations: number;
  population_size: number;
  input_sha256: string;
  scene_revision: number;
}

export interface NativeDesignPayload {
  site_polygon: {type: 'Polygon'; coordinates: number[][][]};
  pnu?: string;
  address?: string;
  constraints?: unknown[];
  job_spec: Record<string, unknown>;
}

export interface NativeDesignJob extends NativeDesignSummary {
  input: NativeDesignPayload;
  prepared: Record<string, unknown>;
  scene_id: string;
}

export interface NativeDesignRequest {request_id: string; scene_revision: number; payload: NativeDesignPayload}

const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);

async function request(projectId: string, path: string, signal: AbortSignal, body?: NativeDesignRequest): Promise<unknown> {
  const response = await fetch(`/api/v1/platform/projects/${encodeURIComponent(projectId)}/design/native-jobs${path}`, {
    signal, method: body ? 'POST' : 'GET', headers: body ? {'Content-Type':'application/json'} : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    if (response.status === 409) throw new Error('장면 버전 또는 저장 요청이 충돌했습니다. 프로젝트의 현재 버전을 확인하세요. 입력은 유지됩니다. (409)');
    if (response.status === 422) {
      const value: unknown = await response.json().catch(() => null);
      const detail = object(value) && object(value.detail) ? value.detail : {};
      const evidence = [typeof detail.code === 'string' ? detail.code.slice(0,100) : '',
        typeof detail.message === 'string' ? detail.message.slice(0,500) : ''].filter(Boolean).join(': ');
      throw new Error(`대지 경계, 제약 조건 또는 설계 옵션을 확인하세요. 입력 명세를 저장하지 못했습니다. (422)${evidence ? ` ${evidence}` : ''}`);
    }
    throw new Error(`설계 명세를 처리하지 못했습니다. 같은 입력으로 다시 저장할 수 있습니다. (${response.status})`);
  }
  return response.json();
}

function summary(value: unknown, projectId: string): NativeDesignSummary {
  const item = value as NativeDesignSummary | null;
  if (!item || item.project_id !== projectId || item.status !== 'created' || item.execution_supported !== false ||
    !['job_id','request_id','created_at','algorithm','building_type','input_sha256'].every(key => typeof item[key as keyof NativeDesignSummary] === 'string') ||
    !/^[a-f0-9]{64}$/.test(item.input_sha256) || !Number.isFinite(item.site_area_m2) || item.site_area_m2 <= 0 ||
    !Number.isInteger(item.scene_revision) || item.scene_revision < 0 ||
    !Number.isInteger(item.max_generations) || !Number.isInteger(item.population_size)) throw new Error('저장된 설계 명세 응답 형식이 올바르지 않습니다.');
  return item;
}

function detail(value: unknown, projectId: string): NativeDesignJob {
  const item = summary(value, projectId) as NativeDesignJob;
  if (!object(item.input) || !object(item.prepared) || typeof item.scene_id !== 'string' || !object(item.input.site_polygon))
    throw new Error('저장된 설계 명세 상세 형식이 올바르지 않습니다.');
  return item;
}

export async function nativeDesignJobs(projectId: string, offset: number, signal: AbortSignal) {
  const value = await request(projectId, `?limit=20&offset=${offset}`, signal);
  if (!object(value) || !Array.isArray(value.items)) throw new Error('신규 설계 명세 목록 형식이 올바르지 않습니다.');
  return value.items.map(item => summary(item, projectId));
}

export async function nativeDesignJob(projectId: string, jobId: string, signal: AbortSignal) {
  const value = detail(await request(projectId, `/${encodeURIComponent(jobId)}`, signal), projectId);
  if (value.job_id !== jobId) throw new Error('요청한 설계 명세와 응답이 일치하지 않습니다.');
  return value;
}

export async function createNativeDesignJob(projectId: string, body: NativeDesignRequest, signal: AbortSignal) {
  const value = detail(await request(projectId, '', signal, body), projectId);
  if (value.request_id !== body.request_id) throw new Error('설계 명세의 저장 요청 ID가 일치하지 않습니다.');
  return value;
}
