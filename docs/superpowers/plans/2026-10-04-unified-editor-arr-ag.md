# Unified Editor ARR AG Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement task-by-task. Keep checkboxes unchecked until the named verification passes. Latest user correction requires per-feature integration into existing backend modules, not a bulk ARR subtree.

**Goal:** ARR·AG·AG-frontend와 기존 Editor 기능을 한 제품으로 통합하고, 외부 공용 Agents는 API/A2A로 연결한다.

**Architecture:** 기존 UI 라우터와 FastAPI 제품 경계를 확장한다. ARR 기능은 기존 `backend/app/modules/{land,regulations,massing,masterplan,parking,elevation}`에 책임별로 통합한다. 원본 트리를 통째로 담는 `backend/arr` 안은 사용자 정정으로 폐기한다. 전문 owner 소스·메모리·환경·실행 DB는 `D:/Data/25_ACE/agents`에 유지한다. ARR/AG 구 경로 의존만 제거하며 공용 agent 연결은 유지한다. 상세: `docs/architecture/2026-10-04-backend-domain-integration.md`.

**Tech Stack:** 현재 고정된 Editor React/Next/Vite/TypeScript, FastAPI, ARR Django/Python, 기존 A2A/LangGraph/MCP와 DB를 유지한다. 통합을 위한 프레임워크 일괄 업그레이드는 하지 않는다.

**Spec:** `docs/architecture/2026-10-04-unified-editor-arr-ag.md`.

## Global Constraints

- 제품 루트는 `D:/Data/25_ACE/editor`, 공용 agent 루트는 `D:/Data/25_ACE/agents`다. agent 소스·환경·메모리·실행 DB는 이전하지 않는다. ARR/AG 원본 폴더는 보호한다.
- 기존 dirty 파일·결과·DB·Git 이력·필수 자산 보존. 전체 root 덮어쓰기, reset/clean, 운영 DB 초기화 금지.
- Windows 기동은 숨김. DB/비밀/venv/node_modules/대용량 결과를 Git에 넣지 않는다.
- 기존 React/Three 버전과 core/viewer 독립성 보존. 원본 프론트 router/provider/lockfile을 그대로 합치지 않는다.
- 모든 활성 기능은 전수 표에 행을 갖는다. health 또는 파일 복사만으로 기능 완료 체크 금지.
- 각 이전 단위는 소스 대응·실행 계약·데이터 보존·검증·rollback·담당 메모리 갱신 후 커밋한다.

## Review Focus

- 같은 project/scene 문자열이 다른 DB에서 다른 대상을 뜻하는 경우 → Task3 소유권/namespace 검증.
- 실행 중 이전, 응답 유실, 중복 재시도 → Task2/4/7 중복 실행·복구 검증.
- Windows 절대경로·junction·cwd와 Django backend namespace 충돌 → Task1/2 새 경로 검증 및 Task4 공용 서비스 연결 검증.
- 좌표/단위/층 불일치, 오래된 scene revision → Task6/7 적용 거절과 멱등 검증.
- 부분 법규·불완전 전문 결과를 완성으로 표시하거나 기존 화면 기능을 누락 → Task1/5/6/8 기능 대응과 판정 보존 검증.

## 진행 방식

각 Task는 별도 검증 가능한 이전 단위다. 큰 Task의 UI/API 작업은 기능 행 하나씩 하위 작업으로 실행한다. source inventory 이후에야 해당 원본의 정확한 파일 복사 목록을 확정한다. 조사 전에 미확인 지원 폴더를 누락하거나 전체 폴더를 제품 코드로 복사하지 않는다.

### Task0 — 서비스 수명·소유권 보호를 먼저 구현

**Files:** `infra/dev/runtime.mjs`, `product.mjs`, `runtime.test.mjs`; 생성 `infra/dev/product-lifecycle.test.mjs`, `infra/config/services.json`.

**Contract:** `{source_owner: editor|agents, lifecycle: session|persistent, management: editor-session|domain-host|agent-host}`. Editor launcher는 editor-session만 start/stop한다. persistent 서비스는 probe-only이며 기동·복구 안내를 제공한다. ARR domain host는 Editor 소스를 사용하지만 공용 소비자가 있으면 persistent다.

- [x] `test_shared_offline_never_spawns`, `test_shutdown_leaves_shared_and_reused_services_running`, `test_ui_exit_keeps_domain_host_alive`를 먼저 실패시킨 뒤 lifecycle 분기를 구현한다. `node --test infra/dev/product-lifecycle.test.mjs infra/dev/runtime.test.mjs` PASS가 gate다.
- [ ] domain→agent→제품 순서의 health와 미기동 시 동작을 정의한다. core 편집 기능이 가능하면 제품을 열되 연결 기능은 unavailable로 표시한다. 공용 서버를 임의 재기동하지 않는다.
- [x] 현재 `product.mjs`가 `ensureService(services.orchestrator)`를 호출해 생성한 API를 shutdown 대상으로 넣는 동작을 제거하는 작업이다. 아직 수정되지 않았음을 운영 기록에 명시하고 검증 후 별도 커밋한다.

2026-10-04 검증: `b5c2c5ea`, `5c800eb8`. dev21 PASS; 실제 격리 HTTP 프로세스로 재사용/공용 서비스 생존 확인. ARR domain→owner→제품 순서 구현. 제품 전체의 미기동 UI 표시는 아직 미검증이므로 Task0 전체 완료는 아니다. 근거: `docs/integrations/2026-10-04-service-lifecycle.md`.

### Task1 — 전수 기능·의존성·복원 기준선

**Files:** 생성 `docs/migrations/unified-function-matrix.json`, `unified-source-map.json`, `infra/migration/unified_inventory.py`, `infra/migration/test_unified_inventory.py`. 기존 `infra/migration` 보존 도구와 AG inventory 재사용.

**Contract:** 기능 행은 `{id,source_root,entrypoint,ui_actions,api_operations,data_owner,target,disposition,status,evidence}`. source map은 `{source,commit,sha256,target,classification}`. classification은 source/required_asset/runtime/research/generated 중 하나다.

- [ ] 원본 라우트·메뉴·handler·API·CLI·등록된 agent를 추출한다. ARR의 inactive API와 Electron 부가 기능도 별도 행으로 남긴다. 미연결/disabled를 동작 중으로 기록하지 않는다.
- [ ] 공용 agents의 원본 ARR/AG 의존도 조사한다. HTTP endpoint와 `ARR_BACKEND`/sys.path/editable install/파일·자산 경로를 나눠 `{consumer,dependency_kind,old_reference,target_reference,compatibility_test}`로 기록한다. Editor 코드 검색만으로 완료하지 않는다.
- [ ] 테스트 `test_every_active_operation_has_a_target`를 먼저 실패시킨 후 누락 행을 채운다. `python -m pytest infra/migration/test_unified_inventory.py -q` 전부 PASS가 첫 gate다.
- [ ] ARR와 모든 owner의 Git 이력·dirty 파일·필수 자산·데이터 snapshot을 보호 위치에 보존하고 복원본 hash를 비교한다. 기존 AG 백업이 ARR 백업을 대체하지 않는다.
- [ ] 원본 D: Editor의 누락된 Gitagent build와 고정 dependencies를 복구한다. `bun run plan:build:agent-runtime`, `python -m pytest backend/tests -q`, 기존 product/browser 명령을 실행해 실패 목록과 원인을 저장한다. 미통과 항목은 이후 검증 baseline에 남긴다.
- [ ] 기능 행/기준선/복원 결과만 커밋. 복원 실패 시 다음 소스 이전 단계로 가지 않는다.

### Task2 — 기능별 계산·자료·저장 소유권을 Editor에 통합

**Files:** 기능별 `backend/app/modules/`, 해당 `api/routes_*.py`, `adapters/`, `backend/tests/`; 대응 기록 `docs/migrations/backend-domain-migrations.json`. 필요한 지속 서비스 설정은 `infra/config/services.json`에서 관리한다. 원본 전체 트리 복사는 하지 않는다.

**Contract:** Task0의 source_owner/lifecycle/management를 사용한다. Editor 소유 서비스는 `{name,source_root,entrypoint,cwd,environment_ref,data_root,health_url,config_id}`, 공용 agent 연결은 endpoint/health/config identity를 등록한다. 제품 source_root만 Editor 상대경로다. 비밀은 environment_ref로만 참조. 기존 Django app label·URL·migration ID 유지.

- [ ] 선택 기능의 자료·소스 복원본 해시와 호출자·저장 영향 범위를 확인한다. 기능별 하위 brief에 source→target과 rollback을 기록한다. 다른 owner를 수정하지 않는 독립 자료 조회부터 시작한다.
- [ ] 원본 URL·체크아웃 없이 해당 Editor API가 동작하는 실패 테스트를 먼저 작성한다. 기능 모듈을 구현하고 완료된 외부 adapter 호출을 제거한다. 원본 응답·오류·필드·자료 판정의 동등성을 검증한다.
- [ ] Django ORM/작업 의존 기능은 복원 DB에서 모델·기존 ID·상태·마이그레이션을 보존하는 저장 계층을 검증한다. FastAPI 안에서 원본 settings를 import하지 않는다.
- [ ] 운영 ARR와 다른 임시 포트/복원 데이터로 기동하고 land/law/design API에 동일 입력을 보내 도메인 값·판정·artifact hash를 비교한다. 시간/새 UUID만 비교 제외 목록으로 명시한다.
- [ ] 비결정적 탐색은 seed·모델·도구 버전·입력 snapshot을 고정한다. 완전 결정화가 불가능한 항목은 면적/충돌/법규 판정 등 사전에 정한 불변 조건과 허용 오차로 비교한다. 기존 실패/부분 결과를 성공으로 바꾸거나 무작위 출력 hash 불일치를 무조건 회귀로 간주하지 않는다.
- [ ] 이전 단위마다 외부 ARR source/HTTP 의존0·필수 자산 누락0을 검증하고 기능표에 실제 완료 범위만 표시한다. 전체 서비스 전환은 모든 단위 검증 이후다.
- [ ] 해당 기능 모듈·API·검증·운영 기록을 커밋한다. 기존18320과 공용 agents는 기능별 전환 검증 전에 자동 교체하지 않는다.

### Task3 — 공통 프로젝트와 데이터 이전

**Files:** 수정 `backend/app/modules/platform/repository.py`, `projects.py`, `schemas/platform.py`; 생성 `modules/platform/source_bindings.py`, `backend/tests/test_source_bindings.py`, `infra/migration/migrate_product_data.py`.

**Contract:** `SourceBinding={project_id,owner_kind,owner_project_id,owner_ref,branch_id,revision,content_hash}`. `ArtifactRef={artifact_id,project_id,run_id,source_binding_id,media_type,content_hash}`. 원본 결과 ID와 신규 제품 ID의 대응을 영속 저장한다.

위 두 DTO의 저장/권한 경계에는 인증된 `consumer_id`와 `principal_id`를 추가한다. 클라이언트가 제출한 scope를 신뢰하지 않는다. owner_project_id/branch와의 매핑은 서버가 결정하며 legacy local 데이터는 명시적 legacy scope로 이관한다. run/artifact/interrupt의 list/get/submit/cancel/resume 모두 같은 검증을 사용한다.

이전 대상은 Editor·ARR·AG 제품 데이터다. 공용 agents 실행 DB·checkpoint·memory는 이전하지 않고 서비스가 제공하는 참조만 제품에 연결한다.

- [ ] 다른 project의 동일 ID 접근거부, 재시도 중복 binding 방지, 이전 후 기존 결과 재열기 테스트를 RED→GREEN으로 구현한다.
- [ ] 실제 DB schema/count/FK/파일 hash를 읽어 restore rehearsal을 수행한다. `python -m pytest backend/tests/test_source_bindings.py -q` PASS, restore 전후 count/FK/hash 일치가 gate다.
- [ ] SQLite online backup 또는 계획된 쓰기 중단으로 데이터 이전. 운영 쓰기 시작 전 원본/신규 중 한 소유자만 선택한다. rollback은 새 쓰기 발생 시 역이전 ledger를 적용한 뒤 전환하도록 기록한다.
- [ ] 데이터 dry-run과 운영 cutover를 분리한다. Task3은 복원 사본으로 검증하고 최종 쓰기 전환은 Task8에서 한다. 전환 시 신규 요청 차단→진행 작업 배출/중단점 기록→DB·artifact 일관 snapshot→검증→endpoint 원자 전환 순서로 수행한다. 새 쓰기 후 rollback은 검증된 역이전이 없으면 읽기 전용으로 멈추고 복구한다. 오래된 DB로 단순 되돌려 새 결과를 잃지 않는다.
- [ ] 변환 도구·schema·증거를 커밋. 데이터를 소스와 함께 커밋하지 않는다.

### Task4 — 공용 Agents 연결·다중 소비자 격리

**Files:** 수정 `backend/app/adapters/orchestrator.py`, `infra/config/services.json`, `infra/dev/runtime.mjs`, `runtime.test.mjs`; 생성 `infra/e2e/agent-connection.spec.mjs`. owner 계약 변경이 필요하면 `D:/Data/25_ACE/agents/<owner>`의 코드/tests/memory에서 수행한다.

**Contract:** agent_id/skill ID/A2A task ID 유지. 공용 서비스 ownership=shared. 소비자/프로젝트 scope는 신뢰할 수 있는 서버 연결·인증 정보로 결정하며 브라우저 임의 값에 맡기지 않는다. 현재 local actor 구성을 다중 소비자 격리 완료로 간주하지 않는다.

- [ ] Editor 종료 시 shared 프로세스를 종료하지 않는 테스트를 RED→GREEN으로 구현한다. 공용 코드·메모리·환경·실행 DB를 Editor에 복사하지 않는다.
- [ ] 실제 도구 호출·source binding·receipt·실행 복구를 검증한다. `node --test infra/e2e/agent-connection.spec.mjs`에서 필수 owner 연결과 미기동 오류 처리를 확인한다.
- [ ] 두 소비자가 같은 요청 키·프로젝트 문자열을 사용해도 작업/결과/취소 범위가 섞이지 않는 계약 테스트를 수행한다. owner의 ARR 호출 설정은 새 Editor domain endpoint로 갱신하되 기존 소비자 계약을 유지한다.
- [ ] Task1에서 찾은 직접 소스 의존과 HTTP 의존을 각각 해소한다. agent→domain 요청이 다시 같은 workflow/agent로 재진입하지 않는 테스트, Editor UI 종료 중 다른 소비자의 실제 작업 완료 테스트를 추가한다. 운영 endpoint 전환은 Task8까지 보류하고 여기서는 격리 설정을 사용한다.
- [ ] 공용 worker 기동·복구는 owner 운영 도구에서 관리한다. Editor의 중복 기동·공용 worker 종료를 방지한다. 제품 연결과 owner 계약 변경은 각각의 저장소에 커밋하고 메모리를 갱신한다. partial/blocked 유지.

### Task5 — ARR 대지·지도·법규 UI 기능 완결

**Files:** 기존 `features/land-analysis`, `backend/app/api/routes_land.py`, `adapters/land.py`; 생성 `features/law/`, `api/routes_law.py`, `adapters/law.py`, `backend/tests/test_law_integration.py`, `infra/e2e/browser/site-law.spec.ts`.

**Contract:** 제품 `/api/v1/land`와 `/api/v1/law`; 프로젝트 SourceBinding/ArtifactRef를 연결한다. ARR의 `assessment`, errors, source 근거를 유지한다. 지도 key는 서버 정책에 따라 전달하며 임의 provider 설정이나 비밀을 로그에 기록하지 않는다.

- [ ] 지도 선택→PNU, 주소 해석, 경계·표고·규제선, 법령 검색/스트림/원문, 결과 저장·재열기 동작을 전수 행별 RED→GREEN으로 이식한다.
- [ ] `site-law.spec.ts`에서 지도/주소/PNU 세 진입을 같은 프로젝트에 연결하고 owner의 부분 결과가 표시되는지 검증한다. 실제 법령 검색과 fixture 검증을 구분한다.
- [ ] 선택된 기능의 모든 사용자 동작이 원본 동등성 표에 PASS가 된 뒤 기능별 커밋. 현재 PNU smoke 결과를 이 단계 전체 완료로 사용하지 않는다.

### Task6 — ARR 설계·매스·BOOK·배치·주차·평면·입면

실행 단위는 6A job/산출물 조회 → 6B BOOK·매스 생성/수정 → 6C 배치·주차 → 6D 평면·입면 → 6E scene 적용으로 나눈다. 각 단위마다 원본 입력/결과 fixture, 정확한 source→target 파일표, API 계약, 실패 테스트, 실제 시나리오와 rollback이 있는 하위 brief를 먼저 작성한다. 이 큰 Task를 한 커밋으로 수행하지 않는다.

**Files:** 기능별 `features/{program,massing,masterplan,parking,elevation}/`; `backend/app/api/routes_design.py`, `adapters/design.py`, `modules/platform/artifacts.py`; `infra/e2e/browser/design-workflow.spec.ts`. 기존 PLANM/DWG/scene 통합 경계를 확장한다.

**Contract:** 제품 실행은 ARR job reference를 반환하고 원본 job 상태·취소·스트림을 보존한다. scene 적용 요청은 `{artifact_id,expected_scene_revision,source_binding_id,idempotency_key}`를 받는다.

- [ ] job 생성/취소/재시도·근거 조회의 계약 테스트부터 구현한다. BOOK/포트폴리오/대안 선택/interactive 수정/SCAD·입면·산출물 export를 기능 행별 연결한다.
- [ ] 배치와 주차의 좌표·단위·층·차량 동선 결과를 2D/3D에서 같은 artifact로 확인한다. source revision 불일치와 재적용 중복을 반드시 테스트한다.
- [ ] `design-workflow.spec.ts`에서 대지→프로그램→매스→배치/주차→평면/입면→scene 저장→재열기를 수행한다. 실패 owner를 mock 성공으로 덮지 않는다.
- [ ] 결과별 검증과 담당 owner 메모리를 갱신하고 기능 행 단위로 커밋한다.

### Task7 — AG 작업 경험·설정·나머지 기존 기능

실행 단위는 7A 일반 요청·메시지·첨부 → 7B 중단/추가 입력·재개 → 7C 이력 비교/export → 7D 설정·팀·허용 MCP·갤러리의 기능 행별 이전이다. 각 단위는 Task6과 같은 하위 brief와 개별 커밋 기준을 따른다. 미확인 메뉴를 빈 화면으로 추가해 완료 처리하지 않는다.

**Files:** `features/agent-workspace/{runs,api}`, `features/settings/`, 기능표에서 확정한 팀/갤러리/도구 모듈; `backend/app/modules/platform/{runs,artifacts}.py`, owner `editor_api.py`; `infra/e2e/browser/agent-workspace.spec.ts`.

**Contract:** 기존 durable run+멱등 키 유지. 추가 입력은 현재 interrupt/source revision을 확인한다. 첨부·메시지·결과·비교·내보내기·권한·설정 저장 계약을 기능표에 기록한다.

- [ ] 일반 요청, 첨부, 메시지 스트림, 중단/재개, 이력 비교/export의 원본 동작별 실패 테스트를 작성하고 UI/API를 함께 이식한다.
- [ ] 팀/MCP/갤러리/모델/표시 설정/기존 Electron 부가 동작은 전수 표를 따라 동등 기능 또는 남은 작업을 명시한다. 실행되지 않던 scheduler를 이식 완료 자동 실행으로 주장하지 않는다.
- [ ] 실서비스 중단·응답 유실·새로고침·권한 변경·잘못된 interrupt를 포함해 `agent-workspace.spec.ts`를 통과시킨다. health-only가 아닌 실제 지원 업무로 검증한다.
- [ ] 기능별 커밋. 도메인 미완성과 제품 연결 미완성을 각각 기록한다.

### Task8 — 최종 폴더명·기동 통합·외부 원본 의존 제거

**Files:** `frontend/app/planm` → `frontend/app/workbench`의 별도 rename; 모든 workspace/dev/build/E2E 경로 참조; `infra/dev/product.mjs`, `infra/config/services.json`; 생성 `infra/migration/verify_self_contained.py`, `infra/e2e/unified-product.config.cjs`.

- [ ] rename 이전/이후 라우트·build·테스트가 동일하게 통과하도록 경로 회귀 테스트를 먼저 작성한다. 기능 변경과 rename을 같은 커밋에 넣지 않는다.
- [ ] 원본 ARR/AG/AG-frontend 경로 없이 새 Editor checkout·제품 복원 데이터에서 기동하고, 별도로 운영 중인 공용 agents에 연결한다. 이전 대상 원본은 삭제하지 않고 격리 환경에서 검증한다.
- [ ] 격리 agent 호스트도 구 ARR/AG 경로가 없는 조건에서 실행한다. 다른 소비자의 기존 API 계약과 Editor API를 함께 검증한 후, Task3의 cutover 절차로 운영 DB/도메인 endpoint를 전환한다. agent 폴더·DB의 위치는 바꾸지 않는다.
- [ ] `python infra/migration/verify_self_contained.py`, backend/owner tests, frontend build, 기존 DWG/PLANM/scene와 신규 E2E를 실행한다. ARR/AG 외부 원본 source 접근0, 공용 agents 연결·소비자 격리 통과, 필수 기능 미검증0이 gate다.
- [ ] 실제 재부팅 복구·백업 복원·rollback 후 같은 프로젝트 결과를 확인한다. 운영 URL/프로세스 identity/로그 위치를 기록한다.
- [ ] 이전 완료 기능표와 최종 메모리를 커밋한다. 원본은 보호된 archive로 남기며 별도 승인 없이 삭제하지 않는다.

## 계획 자체 검토

재검토 후 실행 순서는 **Task0→1→2→3(복원 사본)→4(격리 연결)→5→6A–E→7A–D→8(운영 전환)**이다. 공용 agents는 이동하지 않는다. Task5 이후의 전체 기능 범위는 전수 inventory로 확정하고 기능별 하위 brief를 작성한 뒤 구현한다. 이 계획은 전체 실행 로드맵이며 Task6/7의 개별 코드 작업 지시가 모두 확정됐다는 뜻은 아니다. 체크박스는 모두 아직 미완료다.
