# Lightweight Editor Merge Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. 완료 증거를 확인한 항목만 체크한다.

**Goal:** 경량 AG-frontend의 목록·작업·이력 UI를 Editor 기존 구조에 선별 이식하고, Studio 없이 실제 owner 실행과 연결한다.

**Architecture:** 기존 Vite 라우터와 FastAPI를 확장한다. Editor는 제품 메타데이터와 UI, Orchestrator는 durable 실행, 각 전문 owner는 결과 판단을 소유한다. 첫 진행 표시는 polling이며 SSE는 별도 후속 계약이다.

**Tech Stack:** 현행 React/TypeScript/Vite, FastAPI/Python, SQLite, 기존 Node test·pytest·Playwright. 버전 업그레이드는 포함하지 않는다.

**Spec:** `docs/architecture/editor-agent-folder-structure.md`, `docs/architecture/2026-10-04-editor-platform-design.md`. 이 계획은 기존 전체 계획의 첫 통합 범위를 구체화한다. geometry 적용·전체 전문 기능 완성은 후속이다.

## Global Constraints

- Editor만 최종 제품이며 기존 `/dwg`, `/planm`, `/editor`와 scene 경로를 보존한다.
- 원본·기존 dirty 파일 보존. 전체 AG 복사·원본 삭제·Studio 영구 의존성 금지.
- 구조 문서의 기능별 폴더를 사용한다. 빈 scaffold와 신규 공용 패키지를 먼저 만들지 않는다.
- owner 상태와 transport 상태를 분리한다. Systems·DomainExpert·InteriorDesign의 partial/blocked를 완료로 바꾸지 않는다.
- 숨김 프로세스로 실행하고 각 단계 검증 후 명시적 파일만 커밋한다. push하지 않는다.

## Review Focus

- `/agents-other` 같은 유사 경로, deep link, 뒤로가기: Task 1에서 정확한 segment 매칭.
- owner 정지/미구현: Task 2에서 실제 상태 표시; 성공 mock 대체 금지.
- 다른 프로젝트 run·scene·artifact ID: Task 3/4에서 서버 바인딩 검사.
- 제출 응답 유실·재시작·중복 입력: Task 4에서 durable 멱등성 및 현재 interrupt 검사.
- 전역 CSS 오염·새 의존성·Studio 잔존: Task 5에서 기존 화면 회귀 및 AG 서버 미실행 검증.

### Task 1 — 기존 라우터에 에이전트 화면 추가

**Files:** 수정 `frontend/app/planm/src/app/App.tsx`; 신규 `src/app/routes.ts`, `src/features/agent-workspace/agents/AgentsPage.tsx`, `src/features/agent-workspace/api/{client,types}.ts` (모두 planm 기준). 신규 `infra/e2e/browser/editor-platform.spec.ts`, `infra/e2e/editor-platform.config.cjs`; root `package.json`에 `platform:test:e2e` 추가.

**Interface:** `resolveProductRoute(pathname: string): ProductRoute`; 기존 경로와 신규 `/agents`, `/projects`, `/projects/:projectId`, `/runs/:runId`를 구분하는 discriminated union. 미구현 경로는 완료 화면처럼 만들지 않는다. 기존 default 동작 유지. `listAgents(signal?: AbortSignal): Promise<AgentSummary[]>`는 `/api/v1/platform/agents`만 호출한다.

- [ ] 경로 매칭·deep link·back/forward·요청 실패 브라우저 테스트를 먼저 추가하고 실패 확인.
- [ ] AG `features/agents`의 목록/카드 표현만 추출. 새 route는 lazy import. 전역 Sidebar/router/store 복사 금지. API 미구현 시 명확한 연결 오류 표시.
- [ ] 파일 출처를 `docs/migrations/ag-selected-source-map.json`에 기록. SHA256·원본 commit·target·검증 명령 포함.
- [ ] `npm --prefix frontend/app/planm run build`, `npm --prefix frontend/app/planm run test:boundaries`, `bun run platform:test:e2e -- --grep routing` 통과 후 커밋. E2E config는 새 spec이 실제 discover되도록 testMatch 명시.

### Task 2 — 중앙 catalog 조회 연결

**Files:** 신규 Editor `backend/app/api/routes_platform.py`, `schemas/platform.py`, `adapters/orchestrator.py`; 수정 `backend/app/main.py`; 테스트 `backend/tests/test_platform_agents.py`. Owner 측 신규 `orchestrator/editor_api.py`, `tests/test_editor_api.py`는 `D:/Data/25_ACE/agents/OrchestratorAgent`에 둔다. owner 지침을 읽고 기존 서비스 진입점에 연결한다.

**Interface:** 제품 `GET /api/v1/platform/agents`; owner 내부 `GET /editor/v1/agents`. `AgentSummary = {agent_id, label, capabilities, implementation_status, connection_status, checked_at, evidence_ref}`. 상태는 owner 증거 기반이며 unknown/unavailable/partial을 허용한다. health만으로 verified 호출을 만들지 않는다. 서비스 URL은 서버 설정이며 사용자 입력 URL은 받지 않는다.

- [ ] owner 미가동·catalog 누락·partial·timeout 계약 테스트를 작성해 실패 확인.
- [ ] owner 중앙 catalog를 조회 전용 HTTP로 노출하고 Editor adapter에 timeout/오류 변환 추가. 조회가 설계/큐를 변경하지 않는지 확인.
- [ ] `python -m pytest backend/tests/test_platform_agents.py -q`, owner `python -m pytest tests/test_editor_api.py -q` 통과.
- [ ] 실제 서버 catalog와 화면 목록 대조. AgentSummary 출처와 live 확인 시간을 기록하고 두 저장소를 각각 커밋. 목록 표시만으로 전체 연결 완료 판정 금지.

### Task 3 — 프로젝트 바인딩과 지속 저장

**Files:** 신규 `backend/app/modules/platform/{repository,projects}.py`, `backend/tests/test_platform_projects.py`; routes/schema 확장; frontend `agent-workspace/projects/{ProjectsPage,ProjectPage}.tsx` 및 API 확장.

**Interface:** `GET/POST /api/v1/platform/projects`, `GET /projects/{project_id}`. `ProjectBinding = {project_id, owner_project_id, branch_id, scene_id, scene_revision}`. owner project/branch와 실제 scene 존재·접근 범위를 검증한다. title/브라우저 user_id로 연결하지 않는다. 명시적 `EDITOR_PLATFORM_DATA_DIR` 아래 versioned SQLite에 메타데이터만 저장한다.

- [ ] 임시 DB에서 재시작 유지·잘못된 scene/branch·다른 사용자/프로젝트 접근 거부 테스트 작성 후 실패 확인. 로컬 사용자는 서버에서 결정하고 브라우저 identity override는 거절.
- [ ] 제품 DB와 프로젝트 선택 UI 구현. scene 그래프 및 owner 실행 상태를 이 DB에 복제하지 않는다.
- [ ] `python -m pytest backend/tests/test_platform_projects.py -q` 및 frontend build 통과. 실제 새로고침·재시작으로 binding 보존 확인 후 커밋.

### Task 4 — 실제 요청·진행·추가 입력·이력·결과

**Files:** 신규 `backend/app/modules/platform/{runs,artifacts}.py`, `backend/tests/test_platform_runs.py`, `test_platform_artifacts.py`; owner `editor_api.py` 확장; frontend `agent-workspace/runs/{RunPage,RunList,TaskComposer}.tsx`, API DTO 확장.

**Interface:** 제품 `POST /projects/{project_id}/runs` + `Idempotency-Key`, `GET /projects/{project_id}/runs`, `GET /runs/{run_id}`, `POST /runs/{run_id}/inputs`, `GET /artifacts/{artifact_id}` (모두 platform prefix). owner 내부 같은 run 명령 경계는 `/editor/v1` 사용. POST는 기존 `submit(project, branch, request_id, request)`에 전달하고 202 + durable run_id 반환; HTTP에서 `advance` 실행 금지. 입력은 현재 interrupt_id와 source_versions를 검증해 `queue_resume`로 전달한다. 지원되지 않는 작업/취소는 명시적 미지원 처리.

- [ ] 응답 유실 후 같은 key 재시도=같은 run, 같은 key/다른 payload=409, stale interrupt/source=409, 다른 project run/artifact 조회 거절, owner timeout과 external_outcome_unknown 보존 테스트 작성 후 실패 확인.
- [ ] AG Playground/History의 입력·메시지·목록 표현을 추출한다. owner run polling은 화면에 있는 동안만 실행하고 unmount/프로젝트 변경 시 abort한다. 기존 Studio WS/start·전역 sessionStore 복사 금지.
- [ ] artifact는 owner receipt가 가리키는 허용 결과만 조회하며 hash/source 불일치를 차단한다. Windows 원시 경로를 공개하지 않는다. 설계 geometry 적용 버튼은 이 단계에서 제공하지 않는다.
- [ ] `python -m pytest backend/tests/test_platform_runs.py backend/tests/test_platform_artifacts.py -q`, owner 테스트, frontend build 통과.
- [ ] 격리 프로젝트의 실제 지원 작업으로 제출→worker→A2A receipt→화면→새로고침 후 같은 run 검증. 미완성 owner의 partial/blocked도 확인. 모델 비용이 필요한 작업은 기존 승인 범위 확인 후 실행. 각각 커밋.

### Task 5 — 원본 의존성 제거 확인과 통합 인계

**Files:** 기존 `infra/dev/{product,runtime}.mjs`, 필요한 proxy 설정과 테스트; 신규 E2E spec 확장; 출처 manifest·연결표·Editor와 owner 메모리 갱신.

- [ ] Studio 및 AG-frontend 서버가 꺼진 상태에서 선별한 Editor 화면 전체 흐름 검증. 기존 서비스의 PID identity를 확인하고 소유하지 않은 프로세스를 중단하지 않는다.
- [ ] `bun run platform:test:e2e`, `bun run plan:test:dev`, `bun run plan:test:frontend`, `bun run plan:test:product`, frontend build와 관련 backend 테스트 통과. 사용 환경/실행 명령/실패를 기록한다.
- [ ] `/dwg`, `/planm`, `/editor` 및 scene 2D/3D, 저장·재열기 회귀 확인. 비교 가능한 초기 JS 산출물 크기와 의존성 diff를 기록하고 미채택 Flow/DND/Studio 유입이 없는지 검사한다.
- [ ] 새 경로 설정으로 기동/재시작 및 이전 설정으로 rollback 검증. 원본은 삭제하지 않는다. 연결표는 실제 task/receipt/화면 증거가 있는 행만 검증 완료로 갱신.
- [ ] 코드·출처·검증 결과·담당 메모리를 커밋한다. 전체 에이전트 또는 전문 설계 완성으로 확대 보고하지 않는다.

## 준비 상태와 바로 다음 작업

기능 조사와 폴더 구조·작업 순서는 문서화 완료. 제품 이식은 아직 미실행. 다음 구현은 Task 1 라우터/목록부터 시작하고 Task 2 API로 연결한다. 대형 AG 복원은 별도 보존 검증이며 이 계획의 전체 AG 제품 편입을 뜻하지 않는다. 각 Task를 검증하고 커밋한 뒤 다음 단계로 진행한다.
