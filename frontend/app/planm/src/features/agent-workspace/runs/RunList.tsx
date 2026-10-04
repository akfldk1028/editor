import { useEffect,useState } from 'react';
import { listRuns,runUrl,type RunSummary } from '../api/runs';

export function RunList({projectId,refresh}:{projectId:string;refresh:number}) {
  const [runs,setRuns]=useState<RunSummary[]>([]);
  const [error,setError]=useState<string|null>(null);
  useEffect(() => {
    const controller=new AbortController();setRuns([]);setError(null);
    listRuns(projectId,controller.signal).then(value => {if (!controller.signal.aborted) setRuns(value);})
      .catch(reason => {if (!controller.signal.aborted) setError(String(reason.message));});
    return () => controller.abort();
  },[projectId,refresh]);
  return <section><h2>실행 이력</h2>{error && <p role="alert">{error}</p>}<ul>{runs.map(run =>
    <li key={run.run_id}><a href={runUrl(projectId,run.run_id)}>{run.goal} · {run.status} · {run.run_id}</a></li>)}</ul></section>;
}
