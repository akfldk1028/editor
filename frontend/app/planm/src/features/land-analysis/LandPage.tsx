import {useEffect,useRef,useState} from 'react';
import {analyzeLand,landZones,landStats,type LandResult,type LandZone,type LandStats} from './api';
import './land.css';
import ResolutionLookup from './ResolutionLookup';
import ParcelLookup from './ParcelLookup';

const labels:Record<string,string>={bcr:'건폐율',far:'용적률',height:'높이',sunlight_setback:'일조 이격',
  corner_cutoff:'가각전제',road_diagonal:'도로 사선',building_line:'건축선',adjacent_setback:'인접 대지 이격',
  parking:'주차',landscaping:'조경',limit_pct:'상한 (%)',limit_m:'상한 (m)',min_m:'최소 (m)',setback_m:'이격 (m)',
  article:'근거',rules:'규칙',rule:'규칙',pnu:'PNU',address:'주소',land_area_m2:'대지 면적 (㎡)',source:'출처',
  official_land_price:'공시지가',land_use_situation:'토지 이용',zones:'용도지역',matched:'일치 지역 수',unmatched:'미확인 지역',
  sido:'시도 코드',sigungu:'시군구 코드',eupmyeondong:'읍면동 코드',ri:'리 코드',land_type:'토지 구분 코드',
  land_type_name:'토지 구분',main_number:'본번',sub_number:'부번',success:'조회 성공',name:'이름',
  category:'분류',required:'필수 여부',applies:'적용 여부',direction:'방향',multiplier:'배수',min_pct:'최소 (%)',
  threshold_m2:'면적 기준 (㎡)',applies_when:'적용 조건',allowed_summary:'허용 범위',prohibited_summary:'제한 범위',
  reference_table:'참조표',min_frontage_m:'최소 접도 길이 (m)',min_area_m2:'최소 면적 (㎡)',
  coordinate_x:'X 좌표',coordinate_y:'Y 좌표',sunlight:'일조',building_designation:'건축지정선',
  adjacent_setback_m:'인접 대지 이격 (m)',sunlight_applies:'일조 적용',sunlight_rules:'일조 규칙',notes:'참고'};

function valueText(value:unknown):string {
  if (value===null || value===undefined) return '자료 없음';
  if (typeof value==='boolean') return value?'예':'아니요';
  if (Array.isArray(value)) return value.map(valueText).join(' · ');
  if (typeof value==='object') return Object.entries(value).map(([k,v])=>`${labels[k]||k}: ${valueText(v)}`).join(' / ');
  return String(value);
}
function Fields({value}:{value:Record<string,unknown>|null}) {
  return value ? <dl>{Object.entries(value).map(([key,item])=><div key={key}><dt>{labels[key]||key}</dt><dd>{valueText(item)}</dd></div>)}</dl> : <p>자료 없음</p>;
}

const datumBasis:Record<string,string>={ground_flat:'평탄 대지',ground_weighted_avg:'대지 경계 길이 가중평균',
  ground_split_3m_profile:'대지 경계 표고의 3m 구간별 평균',road_centerline:'도로 중심선',
  road_centerline_weighted_avg:'도로 중심선 가중평균',site_above_road_half_raise:'대지와 도로 고저차의 절반 반영',
  neighbor_avg_86:'대지와 정북 인접지 평균',elevation_fetch_failed:'고도 자료 조회 실패',datum_context_unavailable:'기준 지반고 계산을 위한 필지 자료 없음'};

export default function LandPage() {
  const [input,setInput]=useState('');const [type,setType]=useState<'address'|'pnu'|'raw'>('address');
  const [zone,setZone]=useState('');const [includeLaw,setIncludeLaw]=useState(true);
  const [zones,setZones]=useState<LandZone[]>([]);const [stats,setStats]=useState<LandStats|null>(null);
  const [result,setResult]=useState<LandResult|null>(null);const [busy,setBusy]=useState(false);
  const [error,setError]=useState<string|null>(null);const [metadataErrors,setMetadataErrors]=useState<string[]>([]);
  const [statsError,setStatsError]=useState<string|null>(null);
  const [statsRevision,setStatsRevision]=useState(0);
  const active=useRef<AbortController|null>(null);
  const localAnalysis=result?.execution_owner?result.execution_owner==='editor':type==='raw'&&!includeLaw;
  const canAnalyze=type==='raw'?Boolean(zone):Boolean(input.trim());
  useEffect(()=>{
    const controller=new AbortController();
    const failed=(e:Error)=>{if(!controller.signal.aborted)setMetadataErrors(old=>[...old,e.message]);};
    landZones(controller.signal).then(v=>{if(!controller.signal.aborted)setZones(v);}).catch(failed);
    return ()=>controller.abort();
  },[]);
  useEffect(()=>{
    const controller=new AbortController();
    setStats(null);setStatsError(null);
    landStats(controller.signal,localAnalysis?'editor':'legacy')
      .then(value=>{if(!controller.signal.aborted)setStats(value);})
      .catch(reason=>{if(!controller.signal.aborted)setStatsError(reason instanceof Error?reason.message:'통계 조회 실패');});
    return ()=>controller.abort();
  },[localAnalysis,statsRevision]);
  useEffect(()=>{
    active.current?.abort();setResult(null);setError(null);setBusy(false);
    return ()=>active.current?.abort();
  },[input,type,zone,includeLaw]);
  const regulations=result?.regulations;
  const extended=regulations?.extended as Record<string,unknown>|undefined;
  const landCache=result?.land_info?.cache;
  const datum=result?.setback_lines?.datum_result;
  return <div className="land-analysis"><h1>대지 분석</h1><p>주소·PNU 또는 용도지역으로 대지 정보와 규제 근거를 확인합니다.</p>
    <form onSubmit={async event=>{
      event.preventDefault();if(busy||!canAnalyze)return;
      active.current?.abort();const controller=new AbortController();active.current=controller;
      setBusy(true);setError(null);setResult(null);
      try {
        const value=await analyzeLand({input:type==='raw'?'':input.trim(),input_type:type,zones:zone?[zone]:[],include_law:includeLaw},controller.signal);
        if(!controller.signal.aborted){setResult(value);setStatsRevision(previous=>previous+1);}
      } catch(reason) {if(!controller.signal.aborted)setError(reason instanceof Error?reason.message:'대지 분석 실패');}
      finally {if(!controller.signal.aborted)setBusy(false);}
    }}>
      <label>입력 형식<select value={type} onChange={e=>setType(e.target.value as 'address'|'pnu'|'raw')}><option value="address">주소</option><option value="pnu">PNU</option><option value="raw">용도지역만 분석</option></select></label>
      {type!=='raw'&&<label>주소 또는 PNU<input required maxLength={500} value={input} onChange={e=>{
        const value=e.target.value;setInput(value);setType(/^[0-9]{19}$/.test(value.replace(/-/g,''))?'pnu':'address');
      }}/></label>}
      <label>용도지역 직접 지정<select required={type==='raw'} value={zone} onChange={e=>setZone(e.target.value)}><option value="">{type==='raw'?'용도지역 선택':'자동 조회'}</option>{zones.map(z=><option key={z.zone_name} value={z.zone_name}>{z.zone_name}</option>)}</select></label>
      {type!=='raw'&&<ResolutionLookup input={input} inputType={type}/>}
      <label><input type="checkbox" checked={includeLaw} onChange={e=>setIncludeLaw(e.target.checked)}/>법령 원문 검색</label>
      <button type="submit" disabled={busy||!canAnalyze}>{busy?'분석 중…':'대지 분석'}</button>
    </form>
    {type!=='raw'&&<ParcelLookup input={input} inputType={type}/>}
    {type==='raw'&&<p>필지 위치와 면적이 없는 용도지역 참고 분석입니다. 적용 조례와 필지 조건은 별도로 확인해야 합니다.</p>}
    {metadataErrors.map((message,i)=><p role="status" key={i}>{message}</p>)}
    {error&&<p role="alert">{error}</p>}
    {result&&<>
      {result.storage?.saved===true&&<p role="status">분석 결과를 저장했습니다.</p>}
      {result.storage?.saved===false&&<p role="alert">분석 결과를 저장하지 못했습니다. 현재 결과를 확인한 뒤 다시 시도해 주세요.</p>}
      {landCache?.stale===true&&<p role="alert">최신 토지 정보를 조회하지 못해 이전에 저장한 토지 정보를 사용했습니다.
        {typeof landCache.fetched_at==='string'&&landCache.fetched_at?` 조회 시각: ${landCache.fetched_at}`:' 이전 조회 시각은 확인되지 않았습니다.'}
        {' '}현재 토지 정보와 다를 수 있습니다.</p>}
      <section><h2>분석 판정</h2>{result.assessment?<>
        <p>{result.assessment.status==='needs_evidence'?'추가 근거가 필요합니다.':result.assessment.status}</p>
        <p>{result.assessment.permit_compliance_verified?'ARR에서 허가 적합성 확인을 보고했습니다.':'허가 적합성은 검증되지 않았습니다.'}</p>
        <ul>{result.assessment.missing_evidence.map((v,i)=><li key={i}>{v==='complete_design_applicability_and_permit_checks'?'설계 전체 적용성 및 허가 요건 검토가 필요합니다.':v}</li>)}</ul>
        {result.assessment.scope&&<p>분석 범위: {result.assessment.scope==='regulation_lookup_and_partial_calculation'?'규제 조회 및 일부 계산':result.assessment.scope}</p>}
        <details><summary>조례 및 용도 검토 근거</summary><p>{valueText(result.assessment.municipal_coverage)}</p><p>{valueText(result.assessment.use_permission)}</p></details>
      </>:<p>ARR에서 분석 판정 정보를 제공하지 않았습니다.</p>}</section>
      {result.warning&&<p role="status">{result.warning}</p>}
      {result.errors?.map((message,i)=><p role="alert" key={i}>{message}</p>)}
      <section><h2>필지 정보</h2><Fields value={result.pnu}/><Fields value={result.land_info}/><Fields value={result.zone_info}/></section>
      {datum&&<section aria-labelledby="datum-heading"><h2 id="datum-heading">기준 지반고</h2>
        <dl><div><dt>절대고도</dt><dd>{datum.elevation_source!=='failed'&&typeof datum.elevation_m==='number'&&Number.isFinite(datum.elevation_m)
          ?`${Number(datum.elevation_m.toFixed(3))} m`:'미확인 절대고도'}</dd></div>
          <div><dt>출처</dt><dd>{datum.elevation_source==='failed'?'조회 실패':datum.elevation_source||'미확인'}</dd></div>
          <div><dt>계산 근거</dt><dd>{datumBasis[datum.basis]||datum.basis}</dd></div></dl>
        {datum.elevation_source==='mixed'&&datum.provenance?.providers?.length&&<p>사용한 고도 자료: {datum.provenance.providers.join(' · ')}</p>}
        {datum.provenance?.fallback_used&&<p>대체 고도 자료를 사용했습니다.</p>}
        {datum.notes?.map((note,index)=><p key={index}>{note}</p>)}
      </section>}
      <section><h2>규제 요약</h2>{regulations?Object.entries(regulations).filter(([key])=>key!=='extended').map(([key,value])=>
        <article key={key}><h3>{labels[key]||key}</h3><p>{valueText(value)}</p></article>):<p>확인된 규제 자료가 없습니다.</p>}</section>
      {extended&&<section><h2>추가 규제</h2><Fields value={extended}/></section>}
      <section><h2>법령 근거</h2>{result.law_articles?.articles.map((law,i)=><article key={i}><h3>{law.law_name} {law.article}</h3><p>{law.content}</p></article>)}
        {result.law_articles?.errors.map((message,i)=><p role="alert" key={i}>{message}</p>)}
        {!result.law_articles?.articles.length&&<p>조회된 법령 원문이 없습니다.</p>}</section>
      {result.advisory&&<section aria-labelledby="advisory-heading"><h2 id="advisory-heading">검토용 추출 제안</h2>
        <p>추출 제안은 계산값에 반영되지 않습니다. 적용 조문과 대지 조건을 별도로 검토해야 합니다.</p>
        {result.advisory.status==='unavailable'?<p role="status">추출 제안을 제공할 수 없습니다.</p>:<>
          <p>미검증 제안</p>
          {Object.entries(result.advisory.proposals).map(([kind,proposal])=><article key={kind}>
            <h3>{labels[kind]||kind}</h3><Fields value={proposal}/>
          </article>)}
        </>}
      </section>}
      <section><h2>제한 사항</h2><ul>{result.restrictions.map((v,i)=><li key={i}>{v}</li>)}</ul></section>
    </>}
    <section><h2>{localAnalysis?'Editor 저장 분석 통계':'ARR 분석 통계'}</h2>
      {localAnalysis&&<p>기존 서비스의 과거 분석 기록은 포함하지 않습니다.</p>}
      {statsError&&<p role="status">{statsError}</p>}
      {stats&&<><p>조회 {stats.total_queries}건 · 오류 {stats.error_count}건 · 평균 {stats.avg_response_time_ms}ms</p>
      <ul>{stats.by_input_type.map(v=><li key={v.input_type}>{v.input_type==='address'?'주소':v.input_type==='pnu'?'PNU':'용도지역 직접 지정'}: {v.count}건</li>)}</ul></>}
    </section>
  </div>;
}
