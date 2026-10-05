import { productPath } from '../../../app/product-path';
export type AttemptStatus = 'queued'|'running'|'computed'|'cancelled'|'failed'|'interrupted';
export interface DesignAttempt {
  attempt_id:string; project_id:string; job_id:string; request_id:string; seed:string;
  scene_revision:number; status:AttemptStatus; created_at:string;
}
export interface DesignEvent {sequence:number;type:string;generation?:number;total_evaluated?:number;error?:string}
export interface DesignResult {
  status:'computed'|'cancelled'; total_evaluated:number; legal_compliance_verified:false;
  candidates:Array<{candidate_id:string;geometry:unknown;metrics:Record<string,number>}>;
  rejections:unknown[];
}
const statuses=['queued','running','computed','cancelled','failed','interrupted'];

export function executionAPI(project:string,job:string) {
  const base=productPath(`/api/v1/platform/projects/${encodeURIComponent(project)}/design/native-jobs/${encodeURIComponent(job)}/attempts`);
  async function request(path:string,signal:AbortSignal,body?:unknown) {
    const response=await fetch(base+path,{signal,method:body?'POST':'GET',
      headers:body?{'Content-Type':'application/json'}:undefined,body:body?JSON.stringify(body):undefined});
    if (!response.ok) throw new Error(response.status===409?'실행 또는 장면 상태가 변경되었습니다. 목록을 확인하세요. (409)':`실행 정보를 처리하지 못했습니다. (${response.status})`);
    return response.json();
  }
  function attempt(value:DesignAttempt):DesignAttempt {
    if (!value||value.project_id!==project||value.job_id!==job||!statuses.includes(value.status)||
        !/^[a-f0-9]{32}$/.test(value.attempt_id)||typeof value.seed!=='string') throw new Error('실행 응답의 연결 정보가 올바르지 않습니다.');
    return value;
  }
  return {
    async list(offset:number,signal:AbortSignal):Promise<DesignAttempt[]> {
      const value=await request(`?limit=20&offset=${offset}`,signal);
      if (!Array.isArray(value.items)) throw new Error('실행 목록 형식이 올바르지 않습니다.');
      return value.items.map(attempt);
    },
    async start(body:{request_id:string;scene_revision:number;seed:number;unverified_search:true},signal:AbortSignal) {
      return attempt(await request('',signal,body));
    },
    async cancel(id:string,revision:number,signal:AbortSignal) {
      return attempt(await request(`/${id}/cancel`,signal,{scene_revision:revision}));
    },
    async events(id:string,after:number,signal:AbortSignal):Promise<DesignEvent[]> {
      const value=await request(`/${id}/events?after=${after}`,signal);
      if (!Array.isArray(value.items)||value.items.some((e:DesignEvent,i:number)=>!Number.isInteger(e.sequence)||e.sequence<=after||
          (i>0&&e.sequence<=value.items[i-1].sequence)||typeof e.type!=='string')) throw new Error('실행 기록 형식이 올바르지 않습니다.');
      return value.items;
    },
    async result(id:string,signal:AbortSignal):Promise<DesignResult|null> {
      const value=await request(`/${id}/result`,signal);
      if (value===null) return null;
      if (!['computed','cancelled'].includes(value.status)||value.legal_compliance_verified!==false||
          !Number.isInteger(value.total_evaluated)||!Array.isArray(value.candidates)||!Array.isArray(value.rejections)||
          value.candidates.some((item:any)=>!item||typeof item.candidate_id!=='string'||!item.geometry||
            !item.metrics||typeof item.metrics!=='object'||Array.isArray(item.metrics)||
            Object.values(item.metrics).some(number=>typeof number!=='number'||!Number.isFinite(number))))
        throw new Error('계산 결과 형식이 올바르지 않습니다.');
      return value;
    },
  };
}
