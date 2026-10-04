import type {AlternativesResult, CoreSearchDiagnostic, PlanmRun} from "./types";

const requiredAcceptedCount = 2;

export function HaltEvidence({
  run,
  alternatives,
  designProject,
}: {
  run: PlanmRun;
  alternatives: AlternativesResult | null;
  designProject: string | null;
}) {
  const violations = run.violations ?? [];
  const rejected = alternatives?.rejected_families ?? [];
  return (
    <section className="halt-evidence" aria-label="Halt evidence">
      <div className="halt-heading">
        <div>
          <span>Halted at {run.stage}</span>
          <h3>
            {alternatives
              ? `This mass reached ${alternatives.accepted_count} of ${requiredAcceptedCount} accepted alternatives.`
              : "The run stopped before it produced alternatives."}
          </h3>
        </div>
      </div>
      {violations.length > 0 && (
        <ul className="violation-list">
          {violations.map((violation) => (
            <li key={violation.code}>
              <code>{violation.code}</code>
              <p>{violation.message}</p>
            </li>
          ))}
        </ul>
      )}
      {rejected.length > 0 && (
        <div className="rejected-families">
          <h4>Refused core families</h4>
          <ul>
            {rejected.map((family) => (
              <li key={family.family}>
                <strong>{family.family}</strong>
                {family.reasons.map((reason) => (
                  <span key={reason}>{reason}</span>
                ))}
                {family.diagnostics?.filter(item => item.code === 'no_core_candidates').map((item,index) => (
                  <CoreSearchEvidence key={index} diagnostic={item} />
                ))}
              </li>
            ))}
          </ul>
        </div>
      )}
      {designProject && <p><a href={`/projects/${encodeURIComponent(designProject)}`}>프로젝트의 저장된 설계 다시 보기</a></p>}
    </section>
  );
}

const measure = (value: number) => Number.isFinite(value) ? value.toFixed(2) : '미확인';

function CoreSearchEvidence({diagnostic}: {diagnostic: CoreSearchDiagnostic}) {
  return <section className="core-search-evidence" aria-label="코어 생성 한계 근거">
    <h3>현재 생성기의 코어 후보가 없습니다</h3>
    <p>지원하는 코어 형상으로 후보를 찾지 못했습니다. 생성기 구현의 한계이며, 건물의 법적 불가능 판정이 아닙니다.</p>
    <p>층간 공통 영역: {measure(diagnostic.shared_intersection_area_m2)} m² · 요청 코어 목표 면적: {measure(diagnostic.requested_core_area_m2)} m²</p>
    {diagnostic.shared_intersection_bounds_m && <p>공통 영역 좌표 범위 (m): {diagnostic.shared_intersection_bounds_m.map(measure).join(', ')}</p>}
    <div className="core-search-table"><table>
      <caption>실제로 시도한 코어 검색</caption>
      <thead><tr><th>검색</th><th>최소 폭 × 깊이</th><th>최소 직사각형 면적</th><th>후보 수</th></tr></thead>
      <tbody>{diagnostic.attempts.map((attempt,index) => <tr key={index}>
        <td>{index + 1} · {attempt.widen ? '확장 검색' : '기본 검색'}</td>
        <td>{measure(attempt.minimum_width_m)} × {measure(attempt.minimum_depth_m)} m</td>
        <td>{measure(attempt.minimum_width_m * attempt.minimum_depth_m)} m²</td>
        <td>{attempt.candidate_count}</td>
      </tr>)}</tbody>
    </table></div>
    <p>미확인 규정 사실은 별도로 확인해야 합니다. 이 결과로 형상이나 계획 용도를 변경하지 않습니다.</p>
  </section>;
}
