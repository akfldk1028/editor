import {useEffect,useMemo,useRef,useState} from 'react';
import {executionAPI,type DesignAttempt,type DesignEvent,type DesignResult} from '../api/design-executions';
import {DesignFootprint} from './DesignFootprint';
import './design-execution.css';

const labels={queued:'대기 중',running:'계산 중',computed:'계산 종료',cancelled:'취소됨',failed:'실패',interrupted:'중단됨'};
const active=(value:DesignAttempt)=>value.status==='queued'||value.status==='running';
const errorText=(error:unknown)=>error instanceof Error?error.message:'실행 처리 실패';
const metricLabels:Record<string,string>={floor_area:'연면적 (m²)',bcr:'건폐율 (%)',far:'용적률 (%)',height:'높이 (m)',
  min_setback:'최소 경계 거리 (m)',open_pct:'대지 내 빈 면적 (%)',daylight_score:'일조 대리 지표',compactness:'형상 지표',stepback_factor:'상부 축소 비율'};

export function DesignExecutionPanel({projectId,jobId,revision,algorithm}:{projectId:string;jobId:string;revision:number;algorithm:string}) {
  const api=useMemo(()=>executionAPI(projectId,jobId),[projectId,jobId]);
  const [items,setItems]=useState<DesignAttempt[]|null>(null),[offset,setOffset]=useState(0),[refresh,setRefresh]=useState(0);
  const [selected,setSelected]=useState<string|null>(null),[events,setEvents]=useState<DesignEvent[]>([]);
  const [result,setResult]=useState<DesignResult|null>(null),[candidate,setCandidate]=useState(0);
  const [listError,setListError]=useState(''),[detailError,setDetailError]=useState(''),[actionError,setActionError]=useState('');
  const [seed,setSeed]=useState('42'),[confirmed,setConfirmed]=useState(false),[busy,setBusy]=useState(false);
  const retry=useRef<{seed:number;id:string}|null>(null),pending=useRef(false);
  const lifetime=useRef<AbortController|null>(null);
  const chosen=items?.find(item=>item.attempt_id===selected);
  useEffect(()=>{const controller=new AbortController();lifetime.current=controller;return()=>controller.abort();},[]);
  useEffect(()=>{
    if(algorithm!=='additive')return;
    const controller=new AbortController();let timer:ReturnType<typeof setTimeout>;
    setItems(null);setListError('');
    async function load() {
      let poll=true;
      try {const rows=await api.list(offset,controller.signal);if(!controller.signal.aborted){setItems(rows);setListError('');setSelected(value=>rows.some(row=>row.attempt_id===value)?value:rows[0]?.attempt_id??null);poll=rows.some(active);}}
      catch(error){if(!controller.signal.aborted)setListError(errorText(error));}
      if(!controller.signal.aborted&&poll)timer=setTimeout(load,1000);
    }
    void load();return()=>{controller.abort();clearTimeout(timer);};
  },[api,offset,refresh,algorithm]);
  useEffect(()=>{
    setEvents([]);setResult(null);setCandidate(0);setDetailError('');
    if(!selected)return;
    const controller=new AbortController();let timer:ReturnType<typeof setTimeout>,cursor=0,resultLoaded=false;
    async function load() {
      let poll=true;
      try {
        const rows=await api.events(selected!,cursor,controller.signal);
        if(controller.signal.aborted)return;
        const last = rows[rows.length - 1];
        if(last){cursor=last.sequence;setEvents(value=>[...value,...rows]);}
        if(chosen&&!active(chosen)) {
          if(!resultLoaded){const saved=await api.result(selected!,controller.signal);if(!controller.signal.aborted){setResult(saved);resultLoaded=true;}}
          poll=rows.length===200;
        }
        if(!controller.signal.aborted)setDetailError('');
      } catch(error){if(!controller.signal.aborted)setDetailError(errorText(error));}
      if(!controller.signal.aborted&&poll)timer=setTimeout(load,1000);
    }
    void load();return()=>{controller.abort();clearTimeout(timer);};
  },[api,selected,chosen?.status]);
  async function mutate(cancel=false) {
    const controller=lifetime.current;if(!controller||pending.current)return;
    setActionError('');pending.current=true;setBusy(true);
    try {
      if(cancel&&selected)await api.cancel(selected,revision,controller.signal);
      else {
        const value=Number(seed);
        if(!confirmed||!/^\d+$/.test(seed)||!Number.isSafeInteger(value)||value<0)throw new Error('검증 전 탐색에 동의하고 안전한 범위의 정수 시드를 입력하세요.');
        if(retry.current?.seed!==value)retry.current={seed:value,id:crypto.randomUUID()};
        const saved=await api.start({request_id:retry.current.id,scene_revision:revision,seed:value,unverified_search:true},controller.signal);
        if(!controller.signal.aborted){retry.current=null;setOffset(0);setSelected(saved.attempt_id);}
      }
      if(!controller.signal.aborted)setRefresh(value=>value+1);
    }catch(error){if(!controller.signal.aborted)setActionError(errorText(error));}
    finally{pending.current=false;if(!controller.signal.aborted)setBusy(false);}
  }
  if(algorithm!=='additive')return <p>이 방식은 명세 저장만 지원합니다. 현재 실행 가능한 방식은 additive입니다.</p>;
  const shown=result?.candidates[candidate];
  const progress=[...events].reverse().find(event=>event.type==='generation');
  return <section className="design-execution" aria-label="매스 계산 실행">
    <h4>매스 계산 실행</h4>
    <p>저장된 조건으로 additive 매스를 탐색합니다. 계산 종료는 법규 적합 판정이나 3D 장면 반영을 의미하지 않습니다.</p>
    <label>계산 시드<input value={seed} inputMode="numeric" onChange={e=>setSeed(e.target.value)} disabled={busy}/></label>
    <label className="execution-consent"><input type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/>검증 전 탐색 조건으로 실행합니다</label>
    <button disabled={busy||!confirmed||!items||!!listError||items.some(active)||offset!==0} onClick={()=>void mutate()}>{items?.length?'새 시도로 재실행':'계산 시작'}</button>
    {actionError&&<p role="alert">{actionError}</p>}
    {listError&&<p role="alert">{listError}</p>}
    <button disabled={busy} onClick={()=>setRefresh(value=>value+1)}>실행 목록 새로고침</button>
    <ul>{items?.map(item=><li key={item.attempt_id}>
      <button aria-pressed={selected===item.attempt_id} onClick={()=>setSelected(item.attempt_id)}>실행 보기 · {item.attempt_id}</button>
      <span>{labels[item.status]} · 시드 {item.seed}</span>
    </li>)}</ul>
    <div><button disabled={!items||offset===0} onClick={()=>setOffset(value=>Math.max(0,value-20))}>이전 실행</button>
      <span>{offset/20+1} 페이지</span><button disabled={!items||items.length<20} onClick={()=>setOffset(value=>value+20)}>다음 실행</button></div>
    {chosen&&<article aria-label="선택한 실행">
      <p role="status">실행 상태: {labels[chosen.status]}</p>
      {active(chosen)&&<button disabled={busy} onClick={()=>void mutate(true)}>실행 취소</button>}
      {chosen.status==='queued'&&<p>워커가 작업을 가져오기를 기다립니다. 대기가 계속되면 워커 상태를 확인하세요.</p>}
      {chosen.status==='interrupted'&&<p>워커 연결이 끊어진 시도입니다. 새 시도는 저장된 조건과 선택한 시드로 처음부터 다시 계산합니다.</p>}
      {progress&&<p>진행 세대 {progress.generation} · 평가 {progress.total_evaluated}개</p>}
      {detailError&&<p role="alert">{detailError}</p>}
      <details><summary>실행 기록 ({events.length})</summary><ol>{events.map(event=><li key={event.sequence}>{event.sequence} · {event.type}{event.error&&` · ${event.error}`}</li>)}</ol></details>
      {result&&<div className="execution-result">
        <p>평가 {result.total_evaluated}개 · 후보 기록 {result.candidates.length}개 · 탈락 {result.rejections.length}개</p>
        {result.status==='cancelled'&&<p>취소 시점까지 저장된 부분 결과입니다.</p>}
        {result.candidates.length===0?<p>표시할 후보 형상이 없습니다.</p>:<>
          <label>계산 후보<select value={candidate} onChange={e=>setCandidate(Number(e.target.value))}>{result.candidates.map((item,index)=><option key={item.candidate_id} value={index}>{item.candidate_id}</option>)}</select></label>
          {shown&&<><DesignFootprint geometry={shown.geometry} context={{crs:'EPSG:4326',role:'계산 후보의 저장된 면 형상'}}/>
            <dl>{Object.entries(shown.metrics).map(([name,value])=><div key={name}><dt>{metricLabels[name]??name}</dt><dd>{value}</dd></div>)}</dl></>}
        </>}
      </div>}
    </article>}
  </section>;
}
