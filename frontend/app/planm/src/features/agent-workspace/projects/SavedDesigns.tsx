import {useEffect, useRef, useState} from 'react';
import {archivedDesignJobs, attachDesignJob, designJobDetail, designResultDetail, designResults,
  projectDesignJobs, selectedDesign, selectDesign, type DesignJob, type DesignResult} from '../api/designs';
import type {ProjectBinding} from '../api/projects';
import {DesignFootprint} from './DesignFootprint';
import './saved-designs.css';

const key = (item: {source_id: string; job_id: string}) => JSON.stringify([item.source_id, item.job_id]);
const sameResult = (a: DesignResult | null, b: DesignResult) => a?.result_pk === b.result_pk && key(a) === key(b);
const message = (reason: unknown) => reason instanceof Error ? reason.message : '저장된 설계 조회 실패';
const json = (value: unknown) => value == null ? '저장된 자료 없음' : JSON.stringify(value, null, 2);
const historicalFlag = (value: unknown) => value === true || value === 1 ? '예' : value === false || value === 0 ? '아니요' : '미확인';

export function SavedDesigns({project}: {project: ProjectBinding}) {
  const [jobs, setJobs] = useState<DesignJob[] | null>(null);
  const [selected, setSelected] = useState<DesignResult | null>(null);
  const [activeJob, setActiveJob] = useState<DesignJob | null>(null);
  const [jobDetail, setJobDetail] = useState<DesignJob | null>(null);
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [archiveOffset, setArchiveOffset] = useState(0);
  const [archive, setArchive] = useState<DesignJob[] | null>(null);
  const [resultOffset, setResultOffset] = useState(0);
  const [results, setResults] = useState<DesignResult[] | null>(null);
  const [detail, setDetail] = useState<DesignResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [archiveError, setArchiveError] = useState<string | null>(null);
  const [candidateError, setCandidateError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [detailBusy, setDetailBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const lifetime = useRef<AbortController | null>(null);
  const detailRequest = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController(); lifetime.current = controller;
    setJobs(null); setSelected(null); setActiveJob(null); setDetail(null); setError(null);
    Promise.all([projectDesignJobs(project.project_id, controller.signal), selectedDesign(project.project_id, controller.signal)])
      .then(([items, selection]) => {
        if (controller.signal.aborted) return;
        setJobs(items); setSelected(selection); setDetail(selection);
        if (selection) setActiveJob(items.find(item => key(item) === key(selection)) ?? null);
      }).catch(reason => {if (!controller.signal.aborted) setError(message(reason));});
    return () => {controller.abort(); detailRequest.current?.abort();};
  }, [project.project_id, refresh]);

  useEffect(() => {
    if (!archiveOpen) return;
    const controller = new AbortController(); setArchive(null); setArchiveError(null);
    archivedDesignJobs(project.project_id, archiveOffset, controller.signal)
      .then(value => {if (!controller.signal.aborted) setArchive(value.items);})
      .catch(reason => {if (!controller.signal.aborted) setArchiveError(message(reason));});
    return () => controller.abort();
  }, [project.project_id, archiveOpen, archiveOffset]);

  useEffect(() => {
    if (!activeJob) return;
    const controller = new AbortController(); setResults(null); setJobDetail(null); setCandidateError(null);
    Promise.all([designResults(project.project_id, activeJob, resultOffset, controller.signal),
      designJobDetail(project.project_id, activeJob, controller.signal)])
      .then(([page, job]) => {if (!controller.signal.aborted) {setResults(page.items); setJobDetail(job);}})
      .catch(reason => {if (!controller.signal.aborted) setCandidateError(message(reason));});
    return () => controller.abort();
  }, [project.project_id, activeJob, resultOffset]);

  function openJob(item: DesignJob) {
    detailRequest.current?.abort(); setDetailBusy(false); setActiveJob(item); setResultOffset(0);
    setDetail(selected && key(selected) === key(item) ? selected : null); setNotice(null);
  }

  async function attach(item: DesignJob) {
    const controller = lifetime.current;
    if (!controller || busy) return;
    setBusy(true); setError(null); setNotice(null);
    try {
      await attachDesignJob(project.project_id, item, project.scene_revision, controller.signal);
      const attached = await projectDesignJobs(project.project_id, controller.signal);
      if (!controller.signal.aborted) {setJobs(attached); openJob(item); setNotice('저장된 작업을 프로젝트에 연결했습니다.');}
    } catch (reason) {if (!controller.signal.aborted) setError(message(reason));}
    finally {if (!controller.signal.aborted) setBusy(false);}
  }

  async function openResult(item: DesignResult) {
    detailRequest.current?.abort();
    const controller = new AbortController(); detailRequest.current = controller;
    setDetail(null); setDetailBusy(true); setCandidateError(null); setNotice(null);
    try {const value = await designResultDetail(project.project_id, item, controller.signal);
      if (!controller.signal.aborted) setDetail(value);
    } catch (reason) {if (!controller.signal.aborted) setCandidateError(message(reason));}
    finally {if (!controller.signal.aborted) setDetailBusy(false);}
  }

  async function saveSelection() {
    const controller = lifetime.current;
    if (!controller || !detail || busy) return;
    setBusy(true); setError(null); setNotice(null);
    try {
      const value = await selectDesign(project.project_id, detail, project.scene_revision, controller.signal);
      if (!controller.signal.aborted) {setSelected(value); setNotice('프로젝트의 설계 선택을 저장했습니다.');}
    } catch (reason) {if (!controller.signal.aborted) setError(message(reason));}
    finally {if (!controller.signal.aborted) setBusy(false);}
  }

  return <section className="saved-designs" aria-labelledby="saved-designs-heading">
    <h2 id="saved-designs-heading">저장된 설계</h2>
    <p>가져온 설계 작업과 후보를 확인하고 이 프로젝트에서 사용할 후보를 저장합니다. 보관된 작업은 실행 중인 작업이 아닙니다.</p>
    {error && <p role="alert">{error} <button disabled={busy} onClick={() => setRefresh(value => value + 1)}>저장된 설계 다시 조회</button></p>}
    {notice && <p role="status">{notice}</p>}
    {selected && <p data-testid="saved-design-selection">저장된 선택: {selected.source_id} / {selected.job_id} / 원본 PK {selected.result_pk}
      {' '}<a href={`/planm?designProject=${encodeURIComponent(project.project_id)}`}>선택한 설계로 평면 계획 검토</a></p>}
    <h3>프로젝트에 연결된 작업</h3>
    {!jobs && !error && <p role="status">저장된 작업을 불러오는 중…</p>}
    {jobs?.length === 0 && <p>연결된 설계 작업이 없습니다.</p>}
    <ul>{jobs?.map(item => <li key={key(item)}><p>{item.source_id} / {item.job_id}</p>
      <p>보관됨 · 원본 상태: {item.source_status} · 후보 {item.result_count}개</p>
      <button disabled={busy} onClick={() => openJob(item)} aria-pressed={activeJob ? key(activeJob) === key(item) : false}>후보 보기 · {item.job_id}</button>
    </li>)}</ul>
    <button onClick={() => setArchiveOpen(value => !value)} aria-expanded={archiveOpen}>보관된 작업 찾아보기</button>
    {archiveOpen && <div>
      <h3>가져온 작업 목록</h3>
      {archiveError && <p role="alert">{archiveError}</p>}
      {!archive && !archiveError && <p role="status">작업 목록을 불러오는 중…</p>}
      {archive?.length === 0 && <p>이 범위에 보관된 작업이 없습니다.</p>}
      <ul>{archive?.map(item => {
        const attached = jobs?.some(saved => key(saved) === key(item));
        return <li key={key(item)}><p>{item.source_id} / {item.job_id}</p>
          <p>보관됨 · 원본 상태: {item.source_status} · 후보 {item.result_count}개 · 저장 시각: {item.created_at || '미확인'}</p>
          <button disabled={busy || attached || jobs === null} onClick={() => attach(item)}>{attached ? '연결됨' : '프로젝트에 연결'} · {item.job_id}</button>
        </li>;
      })}</ul>
      <div className="design-pagination"><button disabled={archiveOffset === 0 || !archive} onClick={() => setArchiveOffset(value => Math.max(0, value - 20))}>이전 작업</button>
        <span>{Math.floor(archiveOffset / 20) + 1} 페이지</span><button disabled={!archive || archive.length < 20} onClick={() => setArchiveOffset(value => value + 20)}>다음 작업</button></div>
    </div>}
    {activeJob && <div><h3>설계 후보 · {activeJob.job_id}</h3>
      {candidateError && <p role="alert">{candidateError}</p>}
      {!results && !candidateError && <p role="status">설계 후보를 불러오는 중…</p>}
      {results?.length === 0 && <p>저장된 설계 후보가 없습니다.</p>}
      <ul>{results?.map(item => <li key={item.result_pk}>
        <p>원본 PK {item.result_pk} · 설계 ID {item.design_id ?? '미확인'} · 세대 {item.generation ?? '미확인'}</p>
        <p>원본 적합 판정: {historicalFlag(item.is_feasible)} · 파레토 후보: {historicalFlag(item.is_pareto_optimal)} · 순위: {item.ranking ?? '미확인'}</p>
        <button disabled={busy} onClick={() => openResult(item)}>후보 상세 · 원본 PK {item.result_pk}</button>
        {sameResult(selected, item) && <span>저장된 선택</span>}
      </li>)}</ul>
      <div className="design-pagination"><button disabled={!results || resultOffset === 0} onClick={() => setResultOffset(value => Math.max(0, value - 20))}>이전 후보</button>
        <span>{Math.floor(resultOffset / 20) + 1} 페이지</span><button disabled={!results || results.length < 20} onClick={() => setResultOffset(value => value + 20)}>다음 후보</button></div>
      {jobDetail?.data && <details open><summary>저장된 작업 조건</summary><pre>{json(jobDetail.data.constraints)}</pre>
        <details><summary>원본 작업 명세와 대지</summary><pre>{json({job_spec: jobDetail.data.job_spec, site_polygon: jobDetail.data.site_polygon})}</pre></details>
      </details>}
    </div>}
    {detailBusy && <p role="status">후보 상세를 불러오는 중…</p>}
    {detail && <article className="design-detail" aria-labelledby="design-detail-heading">
      <h3 id="design-detail-heading">설계 후보 상세 · 원본 PK {detail.result_pk}</h3>
      <p>출처 {detail.source_id} · 작업 {detail.job_id} · 설계 ID {detail.design_id ?? '미확인'}</p>
      <DesignFootprint geometry={detail.data?.mass_geojson} context={jobDetail?.data?.coordinate_context ??
        (detail.data?.mass_geojson as Record<string, unknown> | null)?.crs ?? null} />
      <h4>저장된 성능 지표</h4><pre>{json(detail.data?.outputs ?? detail.outputs)}</pre>
      <details><summary>원본 설계 입력</summary><pre>{json(detail.data?.inputs)}</pre></details>
      <p>원본 계산 결과이며 현재 장면의 규제 적합성을 다시 검증한 결과가 아닙니다.</p>
      <button disabled={busy || sameResult(selected, detail)} onClick={saveSelection}>{sameResult(selected, detail) ? '이 후보가 저장되어 있습니다' : '프로젝트 설계로 선택'}</button>
    </article>}
  </section>;
}
