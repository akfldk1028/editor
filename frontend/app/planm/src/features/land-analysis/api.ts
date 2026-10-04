export interface LandResult {
  pnu: Record<string,unknown> | null;
  land_info: (Record<string,unknown>&{cache?:{stale?:boolean;fetched_at?:string;saved?:boolean}}) | null;
  zone_info: Record<string,unknown> | null;
  regulations: Record<string,unknown> | null;
  law_articles: {articles:{law_name:string;article:string;content:string}[];errors:string[];total_count:number}|null;
  restrictions: string[]; errors?:string[]; warning?:string;
  assessment?:{status:string;permit_compliance_verified:boolean;missing_evidence:string[];
    scope?:string;municipal_coverage?:unknown;use_permission?:unknown};
  storage?:{saved:boolean;analysis_id?:string;error?:string};
  execution_owner?:'editor'|'legacy';
  advisory?:{status:'unverified_proposal'|'unavailable';proposals:Record<string,Record<string,unknown>>};
  setback_lines?:{datum_result?:{elevation_m:number|null;elevation_source:string;basis:string;notes?:string[]|null;
    provenance?:{actual_provider?:string|null;providers?:string[];fallback_used?:boolean}|null}|null}|null;
}
export interface LandZone {zone_name:string;bcr_default:number;far_default:number}
export type LandStatsScope = 'editor'|'imported'|'all';
export interface LandStats {total_queries:number;error_count:number;avg_response_time_ms:number;by_input_type:{input_type:string;count:number}[];
  scope?:'editor_local'|'editor_imported'|'editor_all'}
export interface LandInput {input:string;input_type:'address'|'pnu'|'raw';zones:string[];include_law:boolean}

export async function request(path:string,signal:AbortSignal,body?:LandInput|Pick<LandInput,'input'|'input_type'>|{pnu:string}|{x:number;y:number}) {
  const response=await fetch('/api/v1/land/'+path,{signal,method:body?'POST':'GET',
    headers:body?{'Content-Type':'application/json'}:undefined,body:body?JSON.stringify(body):undefined});
  if (!response.ok) throw new Error(`대지 분석 서비스 연결 실패 (${response.status})`);
  return response.json();
}
export async function analyzeLand(body:LandInput,signal:AbortSignal):Promise<LandResult> {
  const value=await request('analyze',signal,body);
  if (!value || !Array.isArray(value.restrictions)) throw new Error('대지 분석 응답 형식이 올바르지 않습니다.');
  if(value.execution_owner!==undefined&&value.execution_owner!=='editor'&&value.execution_owner!=='legacy')
    throw new Error('분석 기록 범위가 올바르지 않습니다.');
  if(value.advisory!==undefined){
    const advisory=value.advisory;
    if(!advisory||!['unverified_proposal','unavailable'].includes(advisory.status)||
      !advisory.proposals||typeof advisory.proposals!=='object'||Array.isArray(advisory.proposals)||
      !Object.values(advisory.proposals).every(proposal=>proposal!==null&&typeof proposal==='object'&&!Array.isArray(proposal)))
      throw new Error('검토용 추출 제안의 응답 형식이 올바르지 않습니다.');
  }
  return value;
}
export async function landZones(signal:AbortSignal):Promise<LandZone[]> {
  const value=await request('zones',signal);
  if (!Array.isArray(value?.zones)) throw new Error('용도지역 응답 형식이 올바르지 않습니다.');
  return value.zones;
}
export async function landStats(signal:AbortSignal,scope:LandStatsScope='all'):Promise<LandStats> {
  return request(`stats?scope=${scope}`,signal);
}

export type LandResolution = {valid:true;parsed:{pnu:string}} | {
  success:boolean;address:string;pnu:string|null;coordinates?:{x:number;y:number};geocoded_address?:string;error?:string;
};
export async function resolveLand(body:{input:string;input_type:'address'|'pnu'},signal:AbortSignal):Promise<LandResolution> {
  const value=await request('resolve',signal,body);
  if(value?.valid===true && typeof value.parsed?.pnu==='string' && /^[0-9]{19}$/.test(value.parsed.pnu)) return value;
  if(typeof value?.success==='boolean' && typeof value.address==='string' &&
    (value.pnu===null || (typeof value.pnu==='string' && /^[0-9]{19}$/.test(value.pnu))) &&
    (!value.success || (Number.isFinite(value.coordinates?.x) && Number.isFinite(value.coordinates?.y))) &&
    (value.geocoded_address===undefined || typeof value.geocoded_address==='string') &&
    (value.error===undefined || typeof value.error==='string')) return value;
  throw new Error('주소/PNU 응답 형식이 올바르지 않습니다.');
}
