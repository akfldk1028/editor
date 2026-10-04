# Editor Platform Integration Implementation Plan

Latest first-slice execution plan: [lightweight merge](2026-10-04-lightweight-editor-merge.md). Folder placement follows [folder structure](../../architecture/editor-agent-folder-structure.md); these supersede whole-source import and premature shared-package steps below.

> **For agentic workers:** Use superpowers:subagent-driven-development or superpowers:executing-plans to execute one reviewed task at a time. This commit contains planning only; unchecked steps have not run.

**Goal:** editor를 유일한 제품으로 삼고, 경량 AG-frontend의 실제 기능을 조사·선별해 프로젝트·편집·에이전트 요청·결과 검토 흐름에 단계적으로 이식한다. AG 원본/이력 보존과 제품 채택은 구분한다.

**Architecture:** 기존 editor UI/scene 저장, FastAPI/PLANM 서비스를 확장한다. Orchestrator는 건축 작업의 durable 실행을, 각 owner는 도메인 판단을 유지한다. 제품 API는 명시적 계약으로 연결한다.

**Tech Stack:** 현재 저장소의 Next/React/Bun/Turbo, Vite, FastAPI/Python, scene SQLite, 기존 LangGraph/A2A. 첫 이전에서 버전 업그레이드나 새 프레임워크를 도입하지 않는다.

**Spec:** [Editor platform design](../../architecture/2026-10-04-editor-platform-design.md).

## Global Constraints

- **최신 사용자 정정:** AG는 최종 제품/별도 서버로 사용하지 않는다. 가볍게 만든 `D:/Data/25_ACE/AG-frontend`를 프론트 조사 기준으로 삼고, 실제 기능과 호출 API를 먼저 조사해 필요한 것만 Editor에 이전한다. 전체 AG 기능 이식, 영구 Studio 서버/프록시, 별도 `/agentlab` 제안은 철회한다. 기능 선별 전 전체 AG를 실제 Editor에 일괄 import하지 않는다. 보존 백업/이력 리허설과 실제 제품 채택을 구분한다.

- 추가 사용자 확정: AG는 Editor에 기능적으로 통합하고 **모든 에이전트를 Editor에 연결**한다. 단순 폴더 이전/외부 콘솔 링크로 완료 처리하지 않는다. 각 agent/capability의 실제 호출·상태·결과 근거가 전체 연결표에 있어야 한다.

- 2026-10-04 사용자 지시: 기존 프론트 라우터에 경로를 추가한다. `/dwg`, `/planm`, `/editor`, 기존 scene 경로를 유지하며 제품 셸에 `/projects`, `/projects/:projectId`, `/agents`, `/runs/:runId`를 추가한다. 전체 셸/라우터 교체는 하지 않는다.

- Windows 실제 루트는 `D:/Data/25_ACE/editor`. 기존 서비스 터미널 창을 띄우지 않는다.
- 사용자 데이터·dirty/untracked/ignored 파일·Git 이력을 보존한다. `git reset --hard`, 원본 history rewrite, 일괄 삭제 금지.
- `AG/`, `AG-frontend/` 원본과 결과물은 먼저 보존한다. 실제 제품 이전은 선별 범위에 한하며, 원본 위치 제거는 별도 작업이다.
- PLANM 및 전문 에이전트는 `D:/Data/25_ACE/agents`의 현재 소유 경계를 유지한다.
- products의 actor/project/scene/provider ID와 revision namespace를 명시한다. Browser email/localStorage는 권한 근거가 아니다.
- blocked/partial/diagnostic 결과는 성공·승인 설계로 자동 승격하지 않는다.
- 코드 구현 전에 최소 실패 테스트를 만들고, 대상 테스트와 실제 흐름을 검증한 뒤 해당 변경만 로컬 커밋한다. upstream push는 범위 밖이다.

## Review Focus

1. 경로 이동 후 DB·artifact 절대경로가 이전 디렉터리를 가리키는 경우: Task1/2 manifest 및 relocation 검사.
2. 프로젝트나 actor가 다른 artifact/run/scene을 요청하는 경우: Task3/5 ACL·ID 매핑 검사.
3. 브라우저 재접속·submit 재전송·worker 재시작: Task4의 멱등성과 cursor replay 검사.
4. stale owner 결과·scene CAS 충돌·진단 proxy: Task5/7에서 자동 적용 거부.
5. Vite/Next origin·basePath·SSR·WS 변경: Task6/8에서 실제 브라우저와 legacy 회귀 검사.

## 순서와 담당

Task1 → Task2 → Task3 → Task4/5 → Task6 → Task7 → Task8 순서다. Task4 owner 작업과 Task5 artifact 조회는 계약이 확정되면 병렬 진행할 수 있다.
Editor 담당은 제품 UI/API/저장·이전 도구, Orchestrator 담당은 실행 서비스 경계, AG 조사 담당은 경량 프론트 기능과 실제 사용 API의 선별·출처 검증, 전문 owner는 도메인 산출물을 맡는다.

### Task 1 — 이전 inventory와 복원 가능한 baseline

**Files:** 새 `infra/migration/inventory.ps1`, `infra/migration/verify-manifest.py`, `infra/migration/tests/test_manifest.py`, `docs/migrations/2026-10-04-source-map.md`. 실제 대용량 snapshot은 Git 밖 전용 migration backup에 둔다.

**Interface:** manifest에 source_root/resolved_root/git_root/commit/branch/index_status/file_kind/relative_path/size/sha256/link_target을 기록한다. secret 파일은 내용 없이 보호된 별도 manifest에 기록한다. destructive mode는 없다.

- [x] fixture로 tracked/dirty/untracked/ignored/공백·한글 경로/reparse point/같은 이름 충돌을 시험한다. 링크는 의도한 루트 밖으로 따라가지 않는다. `93f11598` 기준 전체 migration suite 42개 통과. 실제 대용량 복원 gate는 아래 별도 항목이다.
- [ ] `git -C <source> rev-parse --show-toplevel`, `status --porcelain=v1`, 파일 inventory를 수집한다. AG-frontend는 상위 Git 경로라는 사실을 assert한다.
- [ ] editor/AG/상위 저장소의 Git bundle과 dirty index/worktree patch, 전체 로컬 데이터 snapshot을 별도로 만든다. 복원한 임시 경로에서 파일 해시와 commit을 검사한다.
- [ ] 실행 중 서비스의 실제 command/cwd/DB/artifact 위치·포트·설정 이름을 기록한다. env 비밀 값은 보고서/커밋에 넣지 않는다.
- [ ] 대표 baseline: editor 저장 scene 재열기, PLANM→Pascal 게시, AG 세션/WS, 현재 Sheet 도면·주차·3D. 실행한 결과와 실패를 구분해 저장한다.
- [ ] 도구·manifest 형식·baseline 보고서만 커밋한다. 실패 시 여기서 이동을 중단하고 원본 상태로 조사한다.

### Task 2 — 기능 선별과 필요한 소스·데이터의 보존 이전

**Files:** `docs/integrations/ag-frontend-feature-inventory.md`, `ag-backend-feature-inventory.md`, `docs/migrations/import-manifest.json`; 선별한 제품 소스와 필요한 비교용 보존 경계. 기존 `package.json` glob은 자동 확장하지 않는다.

**Interface:** old_root → new_root, source commit, imported commit, preserved overlay/ignored files, backup location, active runtime path를 기록한다.

- [ ] 임시 clone에서 AG history를 prefix `AG/`에 import하는 rehearsal을 수행한다. AG-frontend는 상위 저장소의 해당 경로 이력만 disposable clone에서 분리한다. 원본 refs는 수정하지 않는다.
- [ ] AG-frontend 실제 라우터·화면·API 호출별로 이전 후보/Editor 중복/보류·제외를 기록하고 채택 범위를 정한다. 모든 기능이 자동 승인된 것으로 간주하지 않는다.
- [ ] editor feature branch에서 선별한 소스를 이전하고 출처 commit/이력을 연결한다. dirty/untracked/ignored 결과와 전체 원본 이력은 별도 보호된 보존 영역에 유지한다. 전체 AG subtree import 리허설 성공을 제품 전체 포함 승인으로 간주하지 않는다.
- [ ] `git ls-files --stage`에서 의도하지 않은160000 gitlink가 없는지, import 후 이력이 조회되는지, 모든 보존 파일의 해시가 일치하는지 검사한다.
- [ ] 새 경로 실행 설정을 준비하되 기존 위치의 서비스를 동시에 중복 실행하지 않는다. API prefix/포트 충돌은 Task8 전까지 독립 profile로 격리한다.
- [ ] 기존 경로를 지우지 않고 이전 manifest·검증된 소스 변경만 커밋한다. rollback은 설정/실행 경로를 기존 위치로 돌리는 절차를 실제 시험한다.

### Task 3 — 영속 제품 프로젝트와 권한 경계

**Files:** 새 `backend/app/schemas/platform.py`, `modules/projects/{service,repository}.py`, `api/routes_platform_projects.py`, `core/platform_auth.py`, `backend/tests/test_platform_projects.py`; 수정 `backend/app/main.py`. 계약 패키지는 `resources/lib/platform-contracts/`에 생성한다.

**Interface:** `Project{id,workspace_id,name,created_at}`, `ProjectBinding{project_id,scene_id,scene_revision,orchestrator_project,branch_id,provider_refs}`. 서버가 검증한 actor를 service에 전달한다. 제품 metadata DB는 scene DB와 분리한다.

- [ ] 프로젝트 생성→프로세스 재시작→조회, 중복 이름과 고유 ID, 교차 프로젝트 거부, 비인증 mutation 거부 실패 테스트부터 작성한다.
- [ ] `/api/v1/platform/projects`와 revision별 매핑을 구현한다. 사용자가 제출한 email로 actor를 대체하지 않는다.
- [ ] existing `createProject` 메모리 placeholder를 제품 registry로 사용하지 않는 것을 테스트한다. 저장 scene의 기존 ID/version은 그대로 참조한다.
- [ ] `python -m pytest backend/tests/test_platform_projects.py backend/tests/test_planm_run_api.py backend/tests/test_pascal_publish_api.py -q`를 실행한다.
- [ ] 로컬 단일 사용자 모드와 운영 인증 요구를 명시한 ADR, migration 및 rollback 절차와 함께 커밋한다.

### Task 4 — Orchestrator owner HTTP 경계와 멱등 실행

추가 산출물: `docs/integrations/agent-connection-matrix.md`. 모든 현재 agent registry/owner manifest를 조사하고 ID·capability·adapter·Editor route·actual task ID·결과 표시·blocked 사유를 매핑한다. 대표 agent 하나만 통과한 것을 전체 연결 완료로 보고하지 않는다.

**Files:** Orchestrator owner의 신규 `orchestrator/service_api.py`, owner `tests/orchestrator/test_service_api.py`; editor 신규 `backend/app/adapters/orchestrator_client.py`, `api/routes_platform_runs.py`, `schemas/platform_runs.py`, `backend/tests/test_platform_runs.py`.

**Interface:** owner service가 기존 `submit(project,branch,request_id,request)`, run/status, queued_input, ordered events를 감싼다. 제품 DTO는 run_id/provider_run_id/source_versions/request_hash/transport_state/owner_status를 구분한다. 미지원 cancel은 capability=false로 반환하며 임의 상태 변경은 하지 않는다.

- [ ] 동일 idempotency key·동일 payload는 같은 run, 다른 payload는409, stale source 거부, actor별 프로젝트 접근 거부 테스트를 만든다.
- [ ] request별 background execution을 새로 만들지 않고 기존 durable queue/worker를 사용한다. editor는 owner DB에 직접 접근하지 않는다.
- [ ] SSE event_id/cursor 재연결, 중복 이벤트, owner timeout 뒤 outcome_unknown, worker 재시작 복구를 검증한다. 알 수 없는 결과를 자동 재전송하지 않는다.
- [ ] 격리 실제 프로젝트로 기존 specialist review/Interior 호출을 수행해 원본 불변과 partial/blocked 보존을 확인한다.
- [ ] owner와 editor에 각각 범위를 나눠 커밋하고, 두 commit과 계약 버전을 상호 기록한다.

### Task 5 — artifact·scene 조회의 첫 세로 기능

**Files:** 신규 `backend/app/modules/artifacts/{service,repository}.py`, `api/routes_platform_artifacts.py`, `backend/tests/test_platform_artifacts.py`; UI 신규 `frontend/app/planm/src/features/agent-workspace/`의 결과 조회 컴포넌트와 client tests.

**Interface:** `ArtifactRef{id,project_id,run_id,kind,sha256,media_type,source_versions,selection_status,diagnostic_only}`. Browser는 opaque ID로 요청한다. 로컬 owner 경로는 서버 내부 매핑에만 둔다.

- [ ] 해시 변조·경로 이탈·다른 project의 artifact·미등록 외부 URI·stale revision 거부 테스트를 만든다.
- [ ] 원본 scene와 owner proposal/diagnostic을 선택적으로 비교한다. 임의 좌표 변환이나 room ID를 프런트에서 생성하지 않는다.
- [ ] 실제 Interior `aca6deae1b9b481e857f1c1b6d32f52d`를 read-only 기준 사례로 사용한다. 파일 해시는 원본 receipt에서 읽고 환경에 맞게 식별자를 매핑한다.
- [ ] 결과가 새 제품 UI에 보이는 첫 milestone을 실제 브라우저로 확인한다. 이 단계에는 설계 적용 mutation이 없다.
- [ ] 저장 scene 재열기와 기존 Pascal 게시 API 회귀를 실행하고 커밋한다.

### Task 6 — 경량 AG-frontend의 선별 기능을 Editor로 이식

Editor의 `/agents`에는 전체 agent와 capability를 제공한다. 선택 agent 호출과 프로젝트 작업, 진행/입력 요청, 결과 근거가 같은 Editor 라우팅 흐름으로 연결돼야 한다. AG 기능은 이 제품 경험에 통합하며, 개발자용 legacy 비교 화면은 최종 통합을 대신하지 않는다.

라우터 추가는 기존 `frontend/app/planm/src/app/App.tsx`의 surface 선택을 확장하는 전용 route matcher로 구현한다. `/projects/:projectId` 등은 segment 단위로 해석해 `/projects-other`를 오인하지 않으며, 기존 앱 링크·back/forward·deep link를 유지한다. 새 라우팅 라이브러리 도입은 필수가 아니다.

**Files:** 경량 `AG-frontend/src/features/*`, `src/shared/api/{client,ws,mcpWs}.ts`의 실제 사용 지점을 근거로 editor 앱 `features/agent-workspace/`와 `backend/app/modules/`에 선별 기능을 이식한다. 해당 기능의 API/회귀 테스트를 추가하고 공개 DTO만 계약 패키지에 둔다. Studio 전체 client/backend를 기본 도입하지 않는다.

**Interface:** agent panel에 project binding, Editor API client, capability와 source revision을 주입한다. 기존 제품 셸의 route/navigation이 소유하며 AG root router를 중첩하지 않는다. 채택 기능은 Editor Backend와 실제 owner 계약을 사용한다. 기존 AG 서버가 꺼진 상태에서도 이전된 기능이 동작해야 한다.

- [ ] 조사표를 기준으로 기능을 고른다. 실행 이력/owner 상태/누락 입력, submit/stream은 우선 후보이며 Team Builder/MCP/Gallery 등은 필요성·중복·의존성을 확인하기 전 자동 포함하지 않는다.
- [ ] i18n/theme/localStorage의 import-time 접근을 SSR 경계 밖으로 옮긴다. 기존 local/sessionStorage 이전 정책과 승인 캐시의 사용자/project scope를 명시한다.
- [ ] `/flow` 팝아웃, BroadcastChannel, `/editor` basePath, 새로고침/뒤로가기, WS 끊김/복구, 승인 재요청을 테스트한다.
- [ ] `bun run check-types`를 별도로 통과시킨다. Next의 `ignoreBuildErrors` 설정 때문에 build 성공만으로 타입 정상 판정하지 않는다.
- [ ] 경량 AG-frontend 기존 `npm run test:unit`, `npm run build`, 관련 E2E와 새 UI 테스트를 비교한다. 제외 기능을 옮긴 것으로 표시하지 않는다. AG 서버가 꺼진 상태에서 채택 기능의 실제 Editor 흐름을 검증한다.
- [ ] 기능 단위 커밋과 source mapping을 남긴다. lockfile/React/Zod/TypeScript 정리는 별도 diff로 하고 초기 이전과 섞지 않는다.

### Task 7 — 명시적 제안 적용과 동시 수정 보호

**Files:** 신규 `backend/app/modules/proposals/service.py`, `api/routes_platform_proposals.py`, `backend/tests/test_platform_proposals.py`, editor 앱의 proposal comparison/apply UI.

**Interface:** expected scene revision + pinned owner artifact/source versions + proposal_id + actor intent를 받는다. 기존 scene expectedVersion/CAS를 사용한다. owner별 적용 지원은 capability로 노출한다.

- [ ] stale source, 다른 branch, scene 동시 수정, 중복 적용, partial/diagnostic의 accepted 설계 오인 테스트를 작성한다.
- [ ] 지원되는 owner 계약만 적용한다. 미완성 Interior/Domain/Systems 결과에 가짜 승인 함수를 만들지 않는다.
- [ ] 실패 후 원본 유지, 적용 전후 scene revision, owner receipt와 actor 감사 기록, 명시적 되돌리기를 검증한다.
- [ ] 실제 프로젝트에서 지원되는 최소 적용 사례를 통과한 뒤 커밋한다. 미지원 도메인은 pending으로 남긴다.

### Task 8 — 단일 진입점 전환·배포·복구

**Files:** 기존 `infra/dev/{product,runtime}.mjs`, `infra/docker/{compose.yml,nginx.conf}`, `infra/e2e/{frontend,product}.config.cjs`, 관련 dev tests; 신규 `infra/e2e/editor-platform.config.cjs`, `infra/e2e/browser/editor-platform.spec.ts`; `package.json`, `docs/SETUP.md`, `docs/STRUCTURE.md`, `.remember/` 인계.

- [ ] 서비스별 URL/cwd/health identity/port를 manifest로 명시한다. ARR은 확인된 별도 주소를 사용하며 PLANM8000과 혼동하지 않는다. 내부 Compose expose와 host publish도 구분한다.
- [ ] 단일 public origin의 `/api/v1/platform`, `/api/v1/planm`, DWG, scene 경로와 필요한 stream이 정확한 owner에 도달하는지 contract test를 만든다. Studio 서버를 기본 기동 목록에 포함하지 않는다.
- [ ] Windows hidden startup, 실제 pid+creation time 기반 stop, 이미 실행 중인 다른 owner를 죽이지 않는 동작을 검사한다. 기존 CLI의 광범위 kill을 통합 launcher에 재사용하지 않는다.
- [ ] 기존 frontend/product Playwright config의 `npm --prefix frontend run dev`를 실제 `frontend/app/planm` 위치로 수정한다. 신규 config는 `testDir: browser`, `testMatch: editor-platform.spec.ts`를 명시하고 `package.json`에 `platform:test:e2e`를 연결한다. 기존 config의 제한된 planm testMatch가 신규 테스트를 건너뛰지 않도록 discovery를 검사한다.
- [ ] `bun run plan:test:dev`, `bun run plan:test:frontend`, `bun run plan:test:product`, backend tests, explicit types, `bun run platform:test:e2e`를 수행한다. 오래된 `plan:test:agent`의 checkout 내부 경로는 외부 PLANM 위치 계약에 맞춘 뒤 실행한다.
- [ ] 실제 project로 저장/재열기→요청→재접속→blocked/partial→artifact 비교→지원되는 apply→재시작을 검증한다. 도면·주차·3D의 기존 회귀도 확인한다.
- [ ] 이전 설정으로 복귀하고 다시 전환하는 rehearsal을 수행한다. 사용자 작업 데이터가 보존됨을 해시와 revision으로 확인한다.
- [ ] 완료 증거·남은 owner 기능·운영 명령·이전 위치 보존 정책을 기록하고 커밋한다. 원본 삭제와 외부 배포는 이 계획에 자동 포함하지 않는다.

## 이번 계획 커밋 검증

문서 링크·참조 경로·현재 Git 경계와 staged diff를 확인한다. 제품 코드와 서비스가 바뀌지 않았으므로 앱 테스트 실행/성공을 주장하지 않는다. 실행 시작점은 Task1이다.
