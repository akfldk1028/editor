import { useEffect, useRef, useState } from 'react';
import { getRunContext, submitHealth, runUrl, type RunContext } from '../api/runs';

export function TaskComposer({projectId,onSubmitted}:{projectId:string;onSubmitted:()=>void}) {
  const [context,setContext] = useState<RunContext | null>(null);
  const [error,setError] = useState<string | null>(null);
  const [busy,setBusy] = useState(false);
  const [url,setUrl] = useState<string | null>(null);
  const [pending,setPending] = useState(false);
  const key = useRef<string>(crypto.randomUUID());
  const active = useRef<AbortController | null>(null);
  const storageKey = `editor:pending-health:${projectId}`;
  useEffect(() => {
    const controller = new AbortController();
    active.current=controller;
    setContext(null);setError(null);setUrl(null);setBusy(false);setPending(false);key.current=crypto.randomUUID();
    try {
      const saved = sessionStorage.getItem(storageKey);
      if (saved) {
        const value = JSON.parse(saved);
        if (typeof value.key !== 'string' || !Number.isInteger(value.context?.scene_revision) ||
          !value.context?.source_versions || typeof value.context.source_versions !== 'object' ||
          Array.isArray(value.context.source_versions) || !Object.values(value.context.source_versions).every(v => Number.isInteger(v) && Number(v) >= 0)) {
          throw new Error('보관된 요청을 읽을 수 없습니다. 실행 이력에서 접수 여부를 확인하세요.');
        }
        key.current=value.key;setContext(value.context);setPending(true);
      } else {
        getRunContext(projectId,controller.signal).then(value => {if (!controller.signal.aborted) setContext(value);})
          .catch(reason => {if (!controller.signal.aborted) setError(String(reason.message));});
      }
    } catch (reason) {setError(reason instanceof Error ? reason.message : '요청 복원 실패');}
    return () => controller.abort();
  },[projectId,storageKey]);
  return <section><h2>작업 요청</h2><p>기본 서비스 상태 점검: Law · MasterPlan · Elevation의 실제 응답을 확인합니다. 설계 생성·변경 작업은 포함하지 않습니다.</p>
    <button disabled={!context || busy} onClick={async () => {
      if (!context || busy) return;
      const controller = active.current;
      setBusy(true);setError(null);
      try {
        sessionStorage.setItem(storageKey,JSON.stringify({key:key.current,context}));
        setPending(true);
        const result = await submitHealth(projectId,context,key.current);
        sessionStorage.removeItem(storageKey);
        if (controller?.signal.aborted) return;
        setPending(false);setUrl(runUrl(projectId,result.run_id));key.current=crypto.randomUUID();onSubmitted();
        setContext(null);
        const updated = await getRunContext(projectId,controller?.signal);
        if (!controller?.signal.aborted) setContext(updated);
      } catch (reason) {if (!controller?.signal.aborted) setError(reason instanceof Error ? reason.message : '요청 실패');}
      finally {if (!controller?.signal.aborted) setBusy(false);}
    }} type="button">{busy ? '요청 확인 중…' : pending ? '이전 요청 다시 확인' : '기본 서비스 상태 점검'}</button>
    {error && <p role="alert">{error}</p>}{url && <p><a href={url}>요청한 실행 열기</a></p>}
  </section>;
}
