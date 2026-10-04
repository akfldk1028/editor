import {useEffect,useState} from 'react';
import {getRun,type RunSummary} from '../api/runs';
import '../agents/agents.css';
import RunCommunications from './RunCommunications';

export default function RunPage({runId}:{runId:string}) {
  const projectId=new URLSearchParams(window.location.search).get('project_id');
  const [run,setRun]=useState<RunSummary|null>(null);
  const [error,setError]=useState<string|null>(null);
  useEffect(() => {
    const controller=new AbortController();let timer:ReturnType<typeof setTimeout>;
    setRun(null);setError(null);
    if (!projectId) {setError('프로젝트 연결이 없는 실행 주소입니다.');return;}
    const poll=async () => {
      try {
        const value=await getRun(projectId,runId,controller.signal);
        if (controller.signal.aborted) return;
        setRun(value);setError(null);
        if (['queued','running','queued_input'].includes(value.status)) timer=setTimeout(poll,1500);
      } catch (reason) {if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '조회 실패');}
    };
    void poll();
    return () => {controller.abort();clearTimeout(timer);};
  },[projectId,runId]);
  return <div className="agent-workspace"><h1>실행 진행</h1>{projectId && <a href={'/projects/'+encodeURIComponent(projectId)}>프로젝트로 돌아가기</a>}
    {error ? <p role="alert">{error}</p> : !run ? <p role="status">실행을 조회하는 중…</p> : <>
      <p>실행 ID: {run.run_id}</p><p>상태: <strong data-testid="run-status">{run.status}</strong></p>
      <p>작업: {run.goal}</p>{run.pending_input && <p>추가 입력이 필요합니다. 입력 응답 화면은 아직 연결되지 않았습니다.</p>}
      <h2>완료된 호출 기록</h2><ul>{run.receipt_task_ids.map(id => <li key={id}>{id}</li>)}</ul>
      <RunCommunications run={run}/>
      <p>실행 상태는 설계 승인이나 전문 분야의 완료를 의미하지 않습니다.</p>
    </>}</div>;
}
