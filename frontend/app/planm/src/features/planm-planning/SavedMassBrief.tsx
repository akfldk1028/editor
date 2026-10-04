import {useState} from 'react';
import type {SavedDesignMass, SavedMassProgram, SprinklerState, TravelLimit} from './types';
import {buildingCodeContext} from './api';
import {DesignFootprint} from '../agent-workspace/projects/DesignFootprint';
import '../agent-workspace/projects/saved-designs.css';

export function SavedMassBrief({projectId, mass, error, busy, onStart}: {
  projectId: string; mass: SavedDesignMass | null; error: string | null; busy: boolean; onStart: (program: SavedMassProgram) => void;
}) {
  const source = mass?.source_provenance;
  const [useType, setUseType] = useState('');
  const [jurisdiction, setJurisdiction] = useState('');
  const [effectiveDate, setEffectiveDate] = useState('');
  const [travelLimit, setTravelLimit] = useState<TravelLimit | ''>('');
  const [sprinkler, setSprinkler] = useState<SprinklerState>('unknown');
  const streets = Array.isArray(mass?.site_edges) ? mass.site_edges.filter(edge => edge?.kind === 'street').length : 0;
  const validUse = useType === 'office' || (useType === 'neighborhood_commercial' && streets === 1);
  return <section aria-labelledby="selected-mass-heading" className="saved-mass-brief">
    <h2 id="selected-mass-heading">선택한 설계로 평면 계획</h2>
    <p><a href={`/projects/${encodeURIComponent(projectId)}`}>프로젝트와 저장된 선택으로 돌아가기</a></p>
    {error && <p role="alert">{error}</p>}
    {!mass && !error && <p role="status">선택한 설계 형상을 불러오는 중…</p>}
    {mass && source && <>
      <p>출처 {source.source.source_id} · 작업 {source.source.job_id} · 원본 PK {source.source.result_pk}</p>
      <p>저장된 층수: {mass.floors} · 높이: {source.height_m} m · 건물 유형: {typeof source.building_type === 'string' ? source.building_type : '미확인'}</p>
      <DesignFootprint geometry={{type: 'Polygon', coordinates: [[...mass.footprint_polygon, mass.footprint_polygon[0]]]}}
        context={{source_crs: source.source_crs, projected_crs: source.projected_crs, units: source.units,
          origin_projected: source.origin_projected, origin_wgs84: source.origin_wgs84}} />
      <details><summary>층별 형상과 출처 확인</summary><pre>{JSON.stringify({floor_footprints: mass.floor_footprints,
        source_provenance: source, building_code_context: mass.building_code_context}, null, 2)}</pre></details>
      <p>저장된 형상과 층별 입력을 그대로 사용합니다. 실행 결과의 미확인 사실과 검증 근거를 검토한 뒤 대안을 승인하세요.</p>
    </>}
    <form onSubmit={event => {
      event.preventDefault();
      if (!mass || error || busy || !validUse) return;
      onStart({use_mix: {[useType]: 1}, building_code_context: buildingCodeContext({jurisdiction,effectiveDate,travelLimit,sprinkler})});
    }}>
      <label>계획 검토 용도<select required disabled={busy || !mass || !!error} value={useType} onChange={event => setUseType(event.target.value)}>
        <option value="">검토할 용도를 직접 선택</option>
        <option value="office">업무시설 (전체 층)</option>
        <option value="neighborhood_commercial" disabled={streets !== 1}>근린생활시설 (전체 층){streets !== 1 ? ' · 도로 접면 입력 필요' : ''}</option>
      </select></label>
      <p>이 실행의 계획 용도를 직접 지정합니다. 원본 건물 유형과 저장된 형상은 변경하지 않습니다.</p>
      {streets !== 1 && <p>근린생활시설 계획에는 확인된 도로 접면이 필요합니다. 저장된 형상에서 도로를 추정하지 않습니다.</p>}
      <details><summary>선택 입력: 규정 검토 사실</summary>
        <label>관할 지역<select value={jurisdiction} disabled={busy} onChange={event => setJurisdiction(event.target.value)}>
          <option value="">미확인</option><option value="KR">대한민국</option>
        </select></label>
        <label>검토 기준일<input type="date" min="2026-02-27" max="2026-07-28" value={effectiveDate} disabled={busy}
          onChange={event => setEffectiveDate(event.target.value)} /></label>
        <label>보행거리 기준<select value={travelLimit} disabled={busy} onChange={event => setTravelLimit(event.target.value as TravelLimit | '')}>
          <option value="">미확인</option><option value="general_30">일반 30m</option>
          <option value="qualified_50">조건 충족 50m</option><option value="highrise_residential_40">고층 주거 40m</option>
        </select></label>
        <label>스프링클러 조건<select value={sprinkler} disabled={busy} onChange={event => setSprinkler(event.target.value as SprinklerState)}>
          <option value="unknown">미확인</option><option value="none">없음</option><option value="standard">일반 설치</option><option value="qualifying">기준 충족 설치</option>
        </select></label>
      </details>
    <button className="primary-action" disabled={busy || !mass || !!error || !validUse} type="submit">
      {busy ? '평면 계획 요청 중…' : '선택한 형상으로 평면 계획 시작'}
    </button>
    </form>
    <p><a href="/planm">새 형상을 직접 입력</a></p>
  </section>;
}
