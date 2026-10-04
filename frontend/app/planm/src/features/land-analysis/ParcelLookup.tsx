import {useEffect,useRef,useState} from 'react';
import {lookupParcel,type ParcelQuery,type ParcelResult} from './parcel-api';
import ParcelPreview from './ParcelPreview';

export default function ParcelLookup({input,inputType}:{input:string;inputType:'address'|'pnu'}) {
  const [longitude,setLongitude]=useState('');const [latitude,setLatitude]=useState('');
  const [result,setResult]=useState<ParcelResult|null>(null);
  const [error,setError]=useState<string|null>(null);const [busy,setBusy]=useState(false);
  const active=useRef<AbortController|null>(null);
  useEffect(()=>{
    active.current?.abort();setResult(null);setError(null);setBusy(false);
    return ()=>active.current?.abort();
  },[input,inputType,longitude,latitude]);
  const pnu=input.trim().replace(/-/g,'');
  const x=Number(longitude),y=Number(latitude);
  const validCoordinates=longitude.trim()!==''&&latitude.trim()!==''&&Number.isFinite(x)&&Number.isFinite(y)&&
    x>=124&&x<=133&&y>=33&&y<=44;
  async function search(query:ParcelQuery){
    active.current?.abort();const controller=new AbortController();active.current=controller;
    setBusy(true);setResult(null);setError(null);
    try{const value=await lookupParcel(query,controller.signal);if(!controller.signal.aborted)setResult(value);}
    catch(reason){if(!controller.signal.aborted)setError(reason instanceof Error?reason.message:'필지 조회 실패');}
    finally{if(!controller.signal.aborted)setBusy(false);}
  }
  return <section aria-labelledby="parcel-heading" aria-busy={busy}>
    <h2 id="parcel-heading">필지 경계 조회</h2>
    <p>위에 입력한 PNU 또는 경위도로 경계를 확인합니다.</p>
    <button type="button" disabled={busy||inputType!=='pnu'||!/^\d{19}$/.test(pnu)} onClick={()=>search({pnu})}>PNU 경계 조회</button>
    <form onSubmit={event=>{event.preventDefault();if(validCoordinates&&!busy)void search({x,y});}}>
      <label>경도<input type="number" step="any" min="124" max="133" required value={longitude} onChange={event=>setLongitude(event.target.value)}/></label>
      <label>위도<input type="number" step="any" min="33" max="44" required value={latitude} onChange={event=>setLatitude(event.target.value)}/></label>
      <button type="submit" disabled={busy||!validCoordinates}>좌표 경계 조회</button>
    </form>
    {busy&&<p role="status">경계를 조회하고 있습니다…</p>}
    {error&&<p role="alert">{error}</p>}
    {result&&<><p role="status">경계 조회 완료</p>{result.address&&<p>{result.address}</p>}
      {result.pnu&&<p>PNU: {result.pnu}</p>}<ParcelPreview geometry={result.geometry}/></>}
  </section>;
}
