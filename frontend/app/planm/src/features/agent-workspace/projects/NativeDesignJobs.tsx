import {useEffect, useRef, useState} from 'react';
import {createNativeDesignJob, nativeDesignJob, nativeDesignJobs, type NativeDesignJob, type NativeDesignPayload,
  type NativeDesignRequest, type NativeDesignSummary} from '../api/native-designs';
import type {ProjectBinding} from '../api/projects';
import {DesignFootprint} from './DesignFootprint';
import {DesignExecutionPanel} from './DesignExecutionPanel';
import './saved-designs.css';
import './native-design-jobs.css';

const buildingTypes = ['공동주택','근린생활시설','업무시설','판매시설','숙박시설','문화집회시설','의료시설','교육연구시설','공장','창고시설'];
const algorithms = [['additive','더하기'],['subtractive','덜어내기'],['grid','격자형'],['lshape','ㄱ자형'],['ushape','ㄷ자형'],
  ['cross','십자형'],['courtyard','중정형'],['tower_podium','타워·저층부'],['hshape','H자형'],['radial','방사형']];
const initialForm = {polygon:'',pnu:'',address:'',buildingType:'',algorithm:'',constraints:'',spec:''};
const message = (reason: unknown) => reason instanceof Error ? reason.message : '설계 명세 처리 실패';
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);

function payload(form: typeof initialForm): NativeDesignPayload {
  let site: unknown, constraints: unknown, spec: unknown;
  try {
    site = JSON.parse(form.polygon);
    constraints = form.constraints.trim() ? JSON.parse(form.constraints) : undefined;
    spec = form.spec.trim() ? JSON.parse(form.spec) : {};
  } catch {throw new Error('대지 경계와 고급 입력의 JSON 문법을 확인하세요.');}
  if (!object(site) || site.type !== 'Polygon' || !Array.isArray(site.coordinates) || site.coordinates.length === 0 ||
    !site.coordinates.every(ring => Array.isArray(ring) && ring.length >= 4 && ring.every(point => Array.isArray(point) && point.length === 2 &&
      Number.isFinite(point[0]) && Math.abs(point[0]) <= 180 && Number.isFinite(point[1]) && Math.abs(point[1]) <= 90) &&
      ring[0][0] === ring[ring.length - 1][0] && ring[0][1] === ring[ring.length - 1][1]))
    throw new Error('WGS84 경도·위도 좌표와 닫힌 경계를 가진 대지 Polygon을 입력하세요.');
  if (site.crs !== undefined) throw new Error('WGS84 경도·위도 좌표로 변환된 Polygon을 입력하세요. 별도 crs 선언은 제거해 주세요.');
  if (!buildingTypes.includes(form.buildingType) || !algorithms.some(([key]) => key === form.algorithm))
    throw new Error('건물 용도와 매스 생성 방식을 직접 선택하세요.');
  if (constraints !== undefined && !Array.isArray(constraints)) throw new Error('제약 조건은 JSON 배열이어야 합니다.');
  if (!object(spec) || (spec.options !== undefined && !object(spec.options))) throw new Error('설계 명세와 options는 JSON 객체여야 합니다.');
  const options = (spec.options ?? {}) as Record<string, unknown>;
  if ((options.building_type !== undefined && options.building_type !== form.buildingType) ||
    (options.algorithm !== undefined && options.algorithm !== form.algorithm))
    throw new Error('고급 입력의 building_type·algorithm은 위에서 선택한 값과 일치해야 합니다.');
  return {site_polygon:site as NativeDesignPayload['site_polygon'],
    ...(form.pnu.trim() ? {pnu:form.pnu.trim()} : {}), ...(form.address.trim() ? {address:form.address.trim()} : {}),
    ...(constraints !== undefined ? {constraints:constraints as unknown[]} : {}),
    job_spec:{...spec,options:{...options,building_type:form.buildingType,algorithm:form.algorithm}}};
}

export function NativeDesignJobs({project}: {project: ProjectBinding}) {
  const [form,setForm] = useState(initialForm);
  const [items,setItems] = useState<NativeDesignSummary[] | null>(null);
  const [offset,setOffset] = useState(0);
  const [refresh,setRefresh] = useState(0);
  const [active,setActive] = useState<string | null>(null);
  const [detail,setDetail] = useState<NativeDesignJob | null>(null);
  const [listError,setListError] = useState<string | null>(null);
  const [detailError,setDetailError] = useState<string | null>(null);
  const [formError,setFormError] = useState<string | null>(null);
  const [busy,setBusy] = useState(false);
  const [notice,setNotice] = useState<string | null>(null);
  const pending = useRef(false);
  const retry = useRef<{key: string; body: NativeDesignRequest} | null>(null);
  const lifetime = useRef<AbortController | null>(null);
  const fileVersion = useRef(0);

  useEffect(() => {
    const controller = new AbortController(); lifetime.current = controller;
    return () => {controller.abort(); fileVersion.current++;};
  }, [project.project_id]);

  useEffect(() => {
    const controller = new AbortController(); setItems(null); setListError(null);
    nativeDesignJobs(project.project_id,offset,controller.signal)
      .then(value => {if (!controller.signal.aborted) setItems(value);})
      .catch(reason => {if (!controller.signal.aborted) setListError(message(reason));});
    return () => controller.abort();
  }, [project.project_id,offset,refresh]);

  useEffect(() => {
    if (!active) return;
    const controller = new AbortController(); setDetail(null); setDetailError(null);
    nativeDesignJob(project.project_id,active,controller.signal)
      .then(value => {if (!controller.signal.aborted) setDetail(value);})
      .catch(reason => {if (!controller.signal.aborted) setDetailError(message(reason));});
    return () => controller.abort();
  }, [project.project_id,active]);

  async function save(event: React.FormEvent) {
    event.preventDefault(); const controller = lifetime.current;
    if (!controller || pending.current) return;
    setFormError(null); setNotice(null);
    let body: NativeDesignRequest;
    try {
      const value = payload(form); const key = JSON.stringify({scene_revision:project.scene_revision,payload:value});
      if (retry.current?.key !== key) retry.current = {key,body:{request_id:crypto.randomUUID(),scene_revision:project.scene_revision,payload:value}};
      body = retry.current.body;
    } catch (reason) {setFormError(message(reason)); return;}
    pending.current = true; setBusy(true);
    try {
      const value = await createNativeDesignJob(project.project_id,body,controller.signal);
      if (!controller.signal.aborted) {
        setActive(value.job_id); setDetail(value); setDetailError(null); setOffset(0); setRefresh(value => value + 1);
        setNotice('설계 명세를 저장했습니다. 상세에서 지원되는 계산을 별도로 시작할 수 있습니다.');
      }
    } catch (reason) {if (!controller.signal.aborted) setFormError(message(reason));}
    finally {pending.current = false; if (!controller.signal.aborted) setBusy(false);}
  }

  async function importFile(file?: File) {
    const version = ++fileVersion.current;
    if (!file) return;
    if (file.size > 1_000_000) {setFormError('대지 GeoJSON 파일은 1 MB 이하로 입력하세요.'); return;}
    try {
      const text = await file.text();
      if (version === fileVersion.current) {setForm(value => ({...value,polygon:text})); setFormError(null);}
    } catch {if (version === fileVersion.current) setFormError('대지 경계 파일을 읽지 못했습니다.');}
  }

  return <section className="native-design-jobs" aria-labelledby="native-design-heading">
    <h2 id="native-design-heading">신규 설계 명세</h2>
    <p className="native-design-state">명세 저장 · additive 계산 지원</p>
    <p>확인한 대지 경계와 설계 조건을 이 프로젝트에 저장합니다. 생성 작업은 시작되지 않으며 설계 결과나 적합성 판정이 만들어지지 않습니다.</p>
    <form onSubmit={save}>
      <fieldset disabled={busy}>
        <legend>대지와 설계 조건</legend>
        <p>대지 경계 Polygon의 WGS84 경도·위도 좌표를 입력하세요. 건물 바닥 형상을 대지로 대신 사용하지 마세요.</p>
        <label>대지 GeoJSON 파일<input type="file" accept=".json,.geojson,application/json,application/geo+json" onChange={event => void importFile(event.target.files?.[0])} /></label>
        <label>대지 경계 GeoJSON (WGS84 Polygon)<textarea required rows={6} value={form.polygon} onChange={event => {fileVersion.current++; setForm({...form,polygon:event.target.value});}} /></label>
        <div className="native-design-fields">
          <label>PNU (선택)<input value={form.pnu} onChange={event => setForm({...form,pnu:event.target.value})} /></label>
          <label>주소 (선택)<input value={form.address} onChange={event => setForm({...form,address:event.target.value})} /></label>
          <label>건물 용도<select required value={form.buildingType} onChange={event => setForm({...form,buildingType:event.target.value})}>
            <option value="">직접 선택</option>{buildingTypes.map(value => <option key={value} value={value}>{value}</option>)}
          </select></label>
          <label>매스 생성 방식<select required value={form.algorithm} onChange={event => setForm({...form,algorithm:event.target.value})}>
            <option value="">직접 선택</option>{algorithms.map(([value,label]) => <option key={value} value={value}>{label} · {value}</option>)}
          </select></label>
        </div>
        <details><summary>고급 입력</summary>
          <p>생략한 값은 저장 시 준비 명세에 기본값이 반영됩니다. 저장 후 원본과 준비 명세를 함께 확인하세요. options의 building_type·algorithm을 입력한다면 위 선택과 일치해야 합니다.</p>
          <label>제약 조건 JSON 배열 (선택)<textarea rows={4} value={form.constraints} onChange={event => setForm({...form,constraints:event.target.value})} /></label>
          <label>설계 명세 JSON 객체 (선택)<textarea rows={5} value={form.spec} onChange={event => setForm({...form,spec:event.target.value})} /></label>
        </details>
        <button type="submit">{busy ? '명세 저장 중…' : '설계 명세 저장'}</button>
      </fieldset>
    </form>
    {formError && <p role="alert">{formError}</p>}
    {notice && <p role="status">{notice}</p>}
    <h3>저장된 신규 명세</h3>
    {listError && <p role="alert">{listError} <button onClick={() => setRefresh(value => value + 1)}>신규 명세 다시 조회</button></p>}
    {!items && !listError && <p role="status">신규 명세를 불러오는 중…</p>}
    {items?.length === 0 && <p>{offset === 0 ? '저장된 신규 설계 명세가 없습니다.' : '이 페이지에 저장된 명세가 없습니다.'}</p>}
    <ul>{items?.map(item => <li key={item.job_id}>
      <p>{item.building_type} · {item.algorithm} · 대지 {item.site_area_m2.toLocaleString(undefined,{maximumFractionDigits:2})} m²</p>
      <small>명세 저장 · {item.created_at}</small>
      <button aria-pressed={active === item.job_id} onClick={() => setActive(item.job_id)}>명세 보기 · {item.job_id}</button>
    </li>)}</ul>
    <div className="native-design-pagination">
      <button disabled={!items || offset === 0} onClick={() => setOffset(value => Math.max(0,value - 20))}>이전 명세</button>
      <span>{Math.floor(offset / 20) + 1} 페이지</span>
      <button disabled={!items || items.length < 20} onClick={() => setOffset(value => value + 20)}>다음 명세</button>
    </div>
    {active && <article className="native-design-detail">
      <h3>저장된 명세 상세</h3>
      {detailError && <p role="alert">{detailError}</p>}
      {!detail && !detailError && <p role="status">명세 상세를 불러오는 중…</p>}
      {detail && <>
        <p>{detail.job_id} · 명세 저장</p>
        <p>{detail.building_type} · {detail.algorithm} · 대지 면적 {detail.site_area_m2.toLocaleString(undefined,{maximumFractionDigits:2})} m²</p>
        <p>준비 명세: 최대 세대 {detail.max_generations} · 개체 수 {detail.population_size}</p>
        <small title={detail.input_sha256}>입력 보존값: {detail.input_sha256.slice(0,12)}… · 장면 버전 {detail.scene_revision}</small>
        <h4>입력한 대지 경계</h4>
        <DesignFootprint geometry={detail.input.site_polygon} context={{crs:'EPSG:4326',coordinates:'경도, 위도',geometry_role:'사용자가 입력한 대지 경계'}} />
        <details open><summary>원본 입력 · 제약 조건과 설계 옵션</summary><pre>{JSON.stringify(detail.input,null,2)}</pre></details>
        <details><summary>준비된 전체 명세</summary><pre>{JSON.stringify(detail.prepared,null,2)}</pre></details>
        <DesignExecutionPanel key={detail.job_id} projectId={project.project_id} jobId={detail.job_id} revision={project.scene_revision} algorithm={detail.algorithm}/>
      </>}
    </article>}
  </section>;
}
