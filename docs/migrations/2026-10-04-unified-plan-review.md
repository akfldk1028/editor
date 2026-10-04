# 통합 계획 재검토

2026-10-04. 사용자 요청에 따라 설계/계획과 현재 코드를 대조한 자체 검토. 이번 변경은 문서 수정이며 기능·서비스 수정을 수행하지 않았다.

| 중요도 | 발견 내용 / 근거 | 계획 수정 |
|---|---|---|
| 높음 | `infra/dev/product.mjs`는 Orchestrator API를 ensureService로 시작하고 새 프로세스를 종료 목록에 넣음. `runtime.mjs`에 owner Python/cwd/args 존재 | Task0 신설. 공용 프로세스 probe-only, 소스 소유와 lifecycle 분리. 현 코드는 아직 변경 필요 |
| 높음 | MasterPlan `config/arr_planning.json`은 ARR18320 사용. Orchestrator `adapters/mass.py`는 ARR_BACKEND 경로와 profile을 검사 | Editor뿐 아니라 공용 agents의 HTTP·직접 import·자산 경로까지 전수 조사. 외부 agent 루트는 유지하되 구 ARR 의존은 제거 |
| 높음 | ARR 계산을 사용하는 공용 agent가 있다면 Editor 세션 종료가 다른 제품의 계산에도 영향 | Editor 소유 domain service도 persistent/domain-host로 운영. UI 종료 중 두 번째 소비자 작업 완료를 검증 |
| 높음 | 현재 `routes_platform_runs.py`는 local actor, owner editor_runs의 key는 project/branch/request_id. 다중 소비자 격리 입증 아님 | Task3에 서버 인증 consumer/principal scope 추가. Task4에서 list/get/cancel/resume까지 교차 소비자 접근 거절 검증 |
| 높음 | 기존 Task3의 운영 데이터 이전이 UI/agent 동등성 검증보다 앞섬. 새 쓰기 이후 오래된 DB로 rollback할 위험 | Task3은 사본 복원 연습. 운영 전환은 Task8. 작업 배출·일관 snapshot·원자 endpoint 전환·역이전 검증 순서 명시 |
| 중간 | agent가 Editor workflow API를 다시 호출하면 순환 실행 가능. 계산 경계와 workflow 경계가 모호 | agent는 계산 전용 domain 경계를 사용. hop/context/deadline 및 비순환 readiness 검증 추가 |
| 중간 | 매스 탐색 등 비결정적 결과에 일괄 artifact hash 동일성 요구 | seed/버전 고정. 불가능한 경우 사전 정의된 불변 조건·오차로 비교하고 검증 근거를 보존 |
| 중간 | Task6/7은 여러 제품 기능이 묶인 큰 작업 | 6A–E, 7A–D로 분리. inventory 이후 파일표·계약·실패 테스트·실제 시나리오가 있는 하위 brief를 작성하고 개별 커밋 |

## 판단

목표 구조는 유지한다: Editor에 ARR/AG 제품 기능을 흡수하고 `D:/Data/25_ACE/agents`는 공용 서비스로 남긴다. 순서를 Task0→inventory/복원→ARR 사본→제품 데이터 사본→공용 연결→기능 이식→최종 운영 전환으로 수정했다.

이 로드맵으로 Task0/1부터 시작할 수 있다. 미조사 기능의 구체 파일 목록이나 Task6/7 하위 구현 설계가 모두 확정된 상태는 아니다. 소스 이전·다중 소비자 격리·최종 통합이 완료됐다는 판정은 하지 않는다. 이번 검증은 문서 일관성 및 코드 대조이며 제품 테스트 재실행은 하지 않았다.
