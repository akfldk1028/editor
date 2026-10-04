import {useEffect,useRef,useState} from 'react';
import {resolveLand,type LandResolution} from './api';

export default function ResolutionLookup({input,inputType}:{input:string;inputType:'address'|'pnu'}) {
  const [result,setResult]=useState<LandResolution|null>(null);
  const [error,setError]=useState<string|null>(null);
  const [busy,setBusy]=useState(false);
  const active=useRef<AbortController|null>(null);
  useEffect(()=>{
    setResult(null);setError(null);setBusy(false);
    return ()=>active.current?.abort();
  },[input,inputType]);
  return <div>
    <button type="button" disabled={busy||!input.trim()} onClick={async()=>{
      active.current?.abort();const controller=new AbortController();active.current=controller;
      setBusy(true);setResult(null);setError(null);
      try {
        const value=await resolveLand({input:input.trim(),input_type:inputType},controller.signal);
        if(!controller.signal.aborted)setResult(value);
      } catch(reason) {
        if(!controller.signal.aborted)setError(reason instanceof Error?reason.message:'주소 확인 실패');
      } finally {if(!controller.signal.aborted)setBusy(false);}
    }}>{busy?'확인 중…':'주소/PNU 확인'}</button>
    {error&&<p role="alert">{error}</p>}
    {result&&('valid' in result
      ? <p role="status">PNU 코드 형식 확인: {result.parsed.pnu}</p>
      : result.success
        ? <p role="status">{result.geocoded_address||result.address} · {result.pnu?`PNU ${result.pnu}`:'PNU 미확인'} · 좌표 {result.coordinates?.x}, {result.coordinates?.y}</p>
        : <p role="alert">{result.error||'주소를 확인하지 못했습니다.'}</p>)}
  </div>;
}
