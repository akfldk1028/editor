import {useEffect, useRef, useState} from 'react';
import {attachExecution, executionArtifactUrl, executionCatalog, executionDetail, projectExecutions,
  type ExecutionArtifact, type ExecutionDetail, type SavedExecution} from '../api/executions';
import type {ProjectBinding} from '../api/projects';
import './saved-executions.css';

const roles: Record<string,string> = {preview:'매스 미리보기',thumbnail:'축소 미리보기',passport:'원본 패스포트',
  execution_manifest:'원본 실행 명세',program:'원본 프로그램',elevation_front:'정면 입면',elevation_right:'우측 입면',
  elevation_back:'후면 입면',elevation_left:'좌측 입면',elevation_top:'상부 뷰',elevation_axon:'등각 뷰',
  proposal:'입면 제안',proposal_front:'제안 정면',proposal_right:'제안 우측',proposal_back:'제안 후면',proposal_left:'제안 좌측',
  proposal_critic_montage:'제안 검토 모음',proposal_evidence:'원본 제안 근거',critic_evidence:'원본 검토 근거',
  portfolio_board:'포트폴리오 보드',geometry_archive:'원본 형상 자료',portfolio_summary:'원본 포트폴리오 요약',run_state:'원본 실행 상태'};
const roleName = (role: string) => roles[role] || '보관 자료';
const message = (reason: unknown) => reason instanceof Error ? reason.message : '보관된 실행 자료 조회 실패';

function ExecutionLabel({item}: {item: SavedExecution}) {
  return <><p>{item.execution_id || '실행 ID 미확인'} · {item.source_namespace}</p>
    <p>보관됨 · 원본 상태: {item.source_status || '미확인'}</p>
    <small title={item.snapshot_sha256}>보존본: {item.snapshot_sha256.slice(0,12)}…</small></>;
}

function ArtifactPreview({projectId, catalogId, item}: {projectId: string; catalogId: string; item: ExecutionArtifact}) {
  const [failed, setFailed] = useState(false);
  return <figure className="execution-preview">
    {failed ? <p role="status">이 이미지를 불러올 수 없습니다. 보관본의 누락 또는 손상을 확인해야 합니다.</p>
      : <img src={executionArtifactUrl(projectId,catalogId,item.artifact_id)} alt={`보관된 ${roleName(item.role)}`} onError={() => setFailed(true)} />}
    <figcaption>{roleName(item.role)} · 원본 기록의 이미지이며 현재 검증 결과가 아닙니다.</figcaption>
  </figure>;
}

export function SavedExecutions({project}: {project: ProjectBinding}) {
  const [attached, setAttached] = useState<SavedExecution[] | null>(null);
  const [attachedOffset, setAttachedOffset] = useState(0);
  const [catalogOpen, setCatalogOpen] = useState(false);
  const [catalogOffset, setCatalogOffset] = useState(0);
  const [catalog, setCatalog] = useState<SavedExecution[] | null>(null);
  const [active, setActive] = useState<string | null>(null);
  const [artifactOffset, setArtifactOffset] = useState(0);
  const [detail, setDetail] = useState<ExecutionDetail | null>(null);
  const [preview, setPreview] = useState<ExecutionArtifact | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const lifetime = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController(); lifetime.current = controller;
    setAttached(null); setError(null); setActive(null); setDetail(null); setPreview(null);
    projectExecutions(project.project_id,attachedOffset,controller.signal)
      .then(items => {if (!controller.signal.aborted) {setAttached(items); setActive(items[0]?.catalog_id ?? null); setArtifactOffset(0);}})
      .catch(reason => {if (!controller.signal.aborted) setError(message(reason));});
    return () => controller.abort();
  }, [project.project_id, attachedOffset, refresh]);

  useEffect(() => {
    if (!catalogOpen) return;
    const controller = new AbortController(); setCatalog(null); setCatalogError(null);
    executionCatalog(project.project_id,catalogOffset,controller.signal)
      .then(value => {if (!controller.signal.aborted) setCatalog(value.items);})
      .catch(reason => {if (!controller.signal.aborted) setCatalogError(message(reason));});
    return () => controller.abort();
  }, [project.project_id,catalogOpen,catalogOffset]);

  useEffect(() => {
    if (!active) return;
    const controller = new AbortController(); setDetail(null); setPreview(null); setDetailError(null);
    executionDetail(project.project_id,active,artifactOffset,controller.signal)
      .then(value => {if (!controller.signal.aborted) {setDetail(value); setPreview(value.items.find(item => item.inline) ?? null);}})
      .catch(reason => {if (!controller.signal.aborted) setDetailError(message(reason));});
    return () => controller.abort();
  }, [project.project_id,active,artifactOffset]);

  async function attach(item: SavedExecution) {
    const controller = lifetime.current;
    if (!controller || busy) return;
    setBusy(true); setError(null); setNotice(null);
    try {
      await attachExecution(project.project_id,item.catalog_id,project.scene_revision,controller.signal);
      const items = await projectExecutions(project.project_id,attachedOffset,controller.signal);
      if (!controller.signal.aborted) {setAttached(items); setActive(item.catalog_id); setArtifactOffset(0); setNotice('보관된 실행 자료를 프로젝트에 연결했습니다.');}
    } catch (reason) {if (!controller.signal.aborted) setError(message(reason));}
    finally {if (!controller.signal.aborted) setBusy(false);}
  }

  return <section className="saved-executions" aria-labelledby="saved-executions-heading">
    <h2 id="saved-executions-heading">보관된 실행 자료</h2>
    <p>가져온 실행 이미지와 근거를 프로젝트 참고 자료로 연결합니다. 저장된 설계 후보와의 연관성은 확인되지 않았습니다.</p>
    {error && <p role="alert">{error} <button disabled={busy} onClick={() => setRefresh(value => value + 1)}>실행 자료 다시 조회</button></p>}
    {notice && <p role="status">{notice}</p>}
    <h3>프로젝트에 연결된 실행 자료</h3>
    {!attached && !error && <p role="status">연결된 실행 자료를 불러오는 중…</p>}
    {attached?.length === 0 && <p>{attachedOffset === 0 ? '연결된 실행 자료가 없습니다.' : '이 범위에 연결된 실행 자료가 없습니다.'}</p>}
    <ul>{attached?.map(item => <li key={item.catalog_id} data-catalog-id={item.catalog_id}>
      <ExecutionLabel item={item} />
      <button disabled={busy} aria-pressed={active === item.catalog_id} onClick={() => {setActive(item.catalog_id); setArtifactOffset(0);}}>실행 자료 보기 · {item.execution_id || item.catalog_id}</button>
    </li>)}</ul>
    <div className="execution-pagination"><button disabled={busy || !attached || attachedOffset === 0} onClick={() => setAttachedOffset(value => Math.max(0,value - 20))}>이전 연결 자료</button>
      <span>{Math.floor(attachedOffset / 20) + 1} 페이지</span><button disabled={busy || !attached || attached.length < 20} onClick={() => setAttachedOffset(value => value + 20)}>다음 연결 자료</button></div>
    <button aria-expanded={catalogOpen} onClick={() => setCatalogOpen(value => !value)}>실행 자료 찾아보기</button>
    {catalogOpen && <div><h3>가져온 실행 보존본</h3>
      {catalogError && <p role="alert">{catalogError}</p>}
      {!catalog && !catalogError && <p role="status">실행 목록을 불러오는 중…</p>}
      {catalog?.length === 0 && <p>이 범위에 보관된 실행 자료가 없습니다.</p>}
      <ul>{catalog?.map(item => {
        const linked = attached?.some(value => value.catalog_id === item.catalog_id);
        return <li key={item.catalog_id} data-catalog-id={item.catalog_id}><ExecutionLabel item={item} />
          <p>미리보기: {item.has_preview ? '보관됨' : '자료 없음'} · 패스포트: {item.has_passport ? '보관됨' : '자료 없음'}</p>
          <button disabled={busy || linked || !attached} onClick={() => attach(item)}>{linked ? '실행 자료 연결됨' : '실행 자료를 프로젝트에 연결'} · {item.execution_id || item.catalog_id}</button>
        </li>;
      })}</ul>
      <div className="execution-pagination"><button disabled={!catalog || catalogOffset === 0} onClick={() => setCatalogOffset(value => Math.max(0,value - 20))}>이전 실행</button>
        <span>{Math.floor(catalogOffset / 20) + 1} 페이지</span><button disabled={!catalog || catalog.length < 20} onClick={() => setCatalogOffset(value => value + 20)}>다음 실행</button></div>
    </div>}
    {active && <article className="execution-detail">
      <h3>실행 보존본 상세</h3>
      {detailError && <p role="alert">{detailError}</p>}
      {!detail && !detailError && <p role="status">실행 자료를 불러오는 중…</p>}
      {detail && <><ExecutionLabel item={detail.execution} />
        <p>원본 기록의 판정과 자료입니다. 실행을 재개하거나 새 이미지를 생성하지 않습니다.</p>
        {detail.execution.geometry_ready !== undefined && <p>원본 기록의 형상 판정: {detail.execution.geometry_ready ? '준비됨' : '미완료'}</p>}
        {detail.execution.replay_reference && <p>원본 재실행 참조 미확인: {detail.execution.replay_reference.source_run_id}</p>}
        {detail.execution.metadata_status && detail.execution.metadata_status !== 'available' && <p>원본 실행 명세를 확인할 수 없습니다.</p>}
        {!detail.execution.has_preview && <p>보관된 매스 미리보기가 없습니다.</p>}
        {!detail.execution.has_passport && <p>보관된 패스포트가 없습니다.</p>}
        {detail.items.length === 0 && <p>이 범위에 표시할 보관 자료가 없습니다.</p>}
        <ul className="execution-artifacts">{detail.items.map(item => <li key={item.artifact_id} data-artifact-id={item.artifact_id}>
          <span>{roleName(item.role)} · {item.size.toLocaleString()} bytes</span>
          {detail.items.filter(other => other.role === item.role).length > 1 && <small title={item.artifact_id}>자료 ID: {item.artifact_id.slice(0,12)}</small>}
          {item.inline && <button aria-pressed={preview?.artifact_id === item.artifact_id} onClick={() => setPreview(item)}>{roleName(item.role)} 보기</button>}
          <a download href={executionArtifactUrl(project.project_id,active,item.artifact_id,true)}>{roleName(item.role)} 다운로드</a>
        </li>)}</ul>
        <div className="execution-pagination"><button disabled={artifactOffset === 0} onClick={() => setArtifactOffset(value => Math.max(0,value - 20))}>이전 자료</button>
          <span>{Math.floor(artifactOffset / 20) + 1} 페이지</span><button disabled={detail.items.length < 20} onClick={() => setArtifactOffset(value => value + 20)}>다음 자료</button></div>
        {preview && <ArtifactPreview key={`${active}:${preview.artifact_id}`} projectId={project.project_id} catalogId={active} item={preview} />}
      </>}
    </article>}
  </section>;
}
