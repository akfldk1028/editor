import type {Communication} from '../api/communications';
import {communicationFlow} from './communication-flow';

export default function RunCommunicationFlow({records,selected,onSelect}:{
  records:Communication[];selected:string|null;onSelect:(agent:string|null)=>void;
}) {
  const {edges,unknown}=communicationFlow(records);
  return <div className="communication-flow" aria-labelledby="flow-heading">
    <h3 id="flow-heading">기록된 협업 흐름</h3>
    <p>에이전트를 선택하면 해당 요청·응답을 볼 수 있습니다. 선은 호출 관계이며 실행 순서나 승인 여부를 뜻하지 않습니다.</p>
    {edges.length>0?<div className="communication-flow-graph">
      <div className="communication-flow-source">orchestrator</div>
      <div className="communication-flow-targets">{edges.map(edge=><div className="communication-flow-edge" key={edge.agent}>
        <span className="communication-flow-arrow" aria-hidden="true">→</span>
        <button type="button" aria-label={`${edge.agent} 호출 ${edge.calls}건 보기`} aria-pressed={selected===edge.agent}
          onClick={()=>onSelect(selected===edge.agent?null:edge.agent)}>
          <strong>{edge.agent}</strong><span>호출 {edge.calls}건 · 응답 본문 {edge.responses}건</span>
        </button>
      </div>)}</div>
    </div>:<p>연결 관계를 표시할 수신 에이전트 기록이 없습니다.</p>}
    {unknown>0&&<p>수신 에이전트가 기록되지 않은 호출 {unknown}건</p>}
    <button type="button" onClick={()=>onSelect(null)} aria-pressed={selected===null}>전체 호출 보기</button>
  </div>;
}
