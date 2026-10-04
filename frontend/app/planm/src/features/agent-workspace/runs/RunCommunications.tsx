import type {Communications} from '../api/communications';
import {useState} from 'react';
import RunCommunicationFlow from './RunCommunicationFlow';
import './communications.css';

export default function RunCommunications({run}:{run:Communications}) {
  const [selected,setSelected]=useState<string|null>(null);
  const active=run.communications.some(record=>record.agent===selected)?selected:null;
  const visible=active?run.communications.filter(record=>record.agent===active):run.communications;
  return <section className="run-communications" aria-labelledby="communications-heading">
    <h2 id="communications-heading">에이전트 대화 기록</h2>
    {!run.communications_available?<p role="status">연결된 서비스가 대화 기록을 제공하지 않습니다.</p>:<>
      <p>이 실행에 저장된 요청·응답입니다. 기록 순서로 표시하며, 실행 중에는 자동 갱신합니다.</p>
      {run.communications_truncated&&<p role="status">최근 100개 호출만 표시합니다.</p>}
      <RunCommunicationFlow records={run.communications} selected={active} onSelect={setSelected}/>
      {!run.communications.length&&<p role="status">아직 기록된 에이전트 호출이 없습니다.</p>}
      {visible.map(message=><article key={message.id}>
        <h3>{message.tool||message.task_id}</h3>
        <p>{message.agent?`orchestrator → ${message.agent}`:'orchestrator → 에이전트 이름 미기록'}</p>
        <p>{message.transport==='a2a'?'A2A 응답 기록':'통신 방식 미확인'} · {message.state==='finished'?'응답 기록됨':message.state==='running'?'호출 진행 중':message.state}</p>
        <details><summary>요청 내용</summary><pre>{message.request_text??'요청 본문이 기록되지 않았습니다.'}</pre></details>
        <details><summary>응답 내용</summary><pre>{message.response_text??'응답 본문이 아직 기록되지 않았습니다.'}</pre></details>
        {message.truncated&&<p>일부 내용이 생략되었습니다.</p>}
      </article>)}
    </>}
  </section>;
}
