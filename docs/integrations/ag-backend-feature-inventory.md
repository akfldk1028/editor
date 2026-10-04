# AG-frontend가 실제 요구하는 백엔드 기능 조사

2026-10-04 · 선택을 위한 소스 조사 · 제품 구현/이관 확정 아님

최종 제품은 Editor 하나다. `D:/Data/25_ACE/AG-frontend`는 사용자가 만든 경량 프런트엔드이며, Studio 자체 프런트엔드와 구분한다. AG는 필요한 기능을 고르는 이전 소스다. 모든 AG 기능을 옮기거나 Studio 서버를 영구 의존성으로 추가하지 않는다. 모든 설계 에이전트를 Editor에서 접근하는 목표와, 범용 AutoGen 기능을 모두 채택하는 결정은 별개다.

## 조사 범위와 증거 수준

- **F** = `D:/Data/25_ACE/AG-frontend`.
- **S** = `D:/Data/25_ACE/AG/autogen_a2a_kit/autogen_source/python/packages/autogen-studio/autogenstudio`.
- **C** = `D:/Data/25_ACE/AG/autogen_a2a_kit/AG_Cohub`.
- **O** = `D:/Data/25_ACE/agents/OrchestratorAgent`.
- **E** = 이 Editor 저장소.

F의 `src/shared/api/{client,ws,mcpWs,arrClient}.ts`, `src/features/agents/api.ts`와 실제 feature 호출부를 기준으로 S의 라우트/런타임을 대조했다. API 래퍼가 있다는 사실, 화면에서 호출한다는 사실, 실제 서버 호출 성공은 다른 증거다. 이번 조사는 소스 읽기만 수행했다. Studio 설치·기동·모델 호출·DB 변경은 하지 않았다. 앞선 복원본 AG-frontend 단위 테스트/빌드 통과는 이 백엔드들의 정상 동작 증거가 아니다.

현재 F의 `vite.config.ts`는 `/api`를 `localhost:8081`로, `/arr`를 `localhost:8000`으로 프록시한다. 후자는 `/arr` 접두사를 제거한다. 이는 개발 설정이며 배포 계약/서비스 가동 증거가 아니다. Editor 백엔드와 8000을 공유하면 충돌할 수 있으므로 주소를 그대로 복사하면 안 된다.

## 실제 기능별 대조와 선택 후보

아래 API는 **현재 AG 계약**이다. Editor의 이미 존재하는 API라는 뜻이 아니다. `/api` 접두사는 S의 `web/app.py` 마운트 기준이다.

| 기능 / F 호출 근거 | 현재 백엔드 및 동작 | Editor/Orchestrator 중복과 선택 후보 |
|---|---|---|
| 에이전트 목록·등록·삭제·상태·컴포넌트 변환: `features/agents/api.ts` | GET `/api/a2a/registry`, POST `/registry/register`, DELETE `/registry/{name}`, POST `/registry/check-all`, GET `/a2a/check?url=…`, GET `/registry/{name}/component`; S `web/routes/a2a.py` | **우선 후보: 목록·기능·상태 표시만.** O의 registry/catalog를 권위로 사용한다. Studio registry를 두 번째 설계 에이전트 등록부로 옮기지 않는다. 임의 URL 등록/체크/코드 생성은 첫 범위 제외. |
| 팀 목록·생성·수정·삭제 및 시각 편집: `features/teams/useTeams.ts`, `team-builder/useTeamEditor.ts` | S `web/routes/teams.py`; GET collection/item, POST collection upsert, DELETE item. 수정도 F에서는 POST `{id,user_id,component}`다. | **보류 후보:** 사용자가 저장한 작업 구성/프리셋 수요가 확인되면 필요한 데이터만 Editor로 추출. AutoGen 팀 그래프를 건축 실행 DAG나 owner 권한으로 취급하지 않는다. |
| 세션·과거 실행과 메시지: F `client.ts` session API, playground | S `web/routes/sessions.py`; GET/POST collection, GET/PUT/DELETE item, GET `/{id}/runs`. Studio 숫자 ID와 team_id 기반. | **우선 후보:** 프로젝트에 연결된 대화/요청 기록 UX. Editor 제품 메타데이터로 필요한 부분을 구현하되 O run ID 참조를 저장. 세션을 건축 project/branch와 동일시하지 않는다. |
| 실행 시작·토큰/메시지 스트림·사용자 입력·중지: `features/playground/PlaygroundPage.tsx`, `shared/api/ws.ts` | POST `/api/runs/`는 `{session_id,user_id}`로 CREATED 행을 만든다. WS `/api/ws/runs/{run_id}`의 `start`가 task/files/team_config를 보내고 `asyncio.create_task`로 실제 실행. `stop`, `input_response`, `ping` 지원. S `web/routes/{runs,ws}.py`, `web/managers/connection.py`, `teammanager/teammanager.py`. | **우선 후보: 진행·결과·추가 입력 UX만 재사용.** 실행은 O durable queue. Studio의 프로세스 내부 task/cancellation token을 두 번째 큐로 가져오지 않는다. O에 동일한 취소 지원이 있다고 표시하지 않는다. |
| 도구 승인 UI: `features/tool-approval/tool-approval.hooks.ts` | WS `input_response`에 응답을 보낸다. 독립적인 건축 승인/법규 gate 계약은 아니다. | **재설계 후보:** owner interrupt ID, project/branch/source revision에 묶인 입력으로 변환. 도구 실행 허가를 설계 승인·issue closure로 표시하지 않는다. |
| 갤러리·템플릿 가져오기: `features/gallery/useGallery.ts` | GET `/api/gallery/`; 템플릿 가져오기는 `teamAPI.create`. URL 동기화는 **브라우저가 URL에 직접 fetch**한다. S gallery CRUD 라우트도 있으나 전체 CRUD를 화면 사용으로 단정하지 않는다. | **보류 후보:** 검토한 작업 프리셋만 필요 여부 선택. AutoGen 기본 갤러리 전체, 외부 URL 자동 동기화는 필수 아님. URL fetch에 공통 auth 헤더를 붙이는 기존 패턴도 그대로 이전하지 않는다. |
| 컴포넌트 검증/실행 테스트: TeamsPage, `useTeams.ts`, `gallery/components/GalleryDetail.tsx` | POST `/api/validate/`와 `/api/validate/test`; S `validation/{validation_service,component_test_service}.py`. 후자는 timeout과 선택 model_client로 실제 기능 테스트를 호출한다. | **분리 선택:** 정적 계약 검증은 유용. 모델/도구를 실행하는 범용 테스트는 첫 범위 제외. 연결 점검 버튼으로 유료 모델/임의 도구가 실행되면 안 된다. |
| MCP 서버 연결·도구 목록·호출: `features/mcp/McpPage.tsx`, `shared/api/mcpWs.ts` | WS `/api/mcp/ws/{session_id}?server_params=…`; S `web/routes/mcp.py`가 MCP 세션/브리지를 만든다. HTTP connect/status 라우트도 있지만 F의 주 경로는 WS다. | **부분 후보:** Editor 기존 `backend/mcp`의 scene 작업을 우선 사용. 범용 stdio 명령/외부 서버 연결 UI는 필요성이 확인될 때 별도 제한 계약으로 검토. Studio MCP 브리지를 영구 의존성으로 두지 않는다. |
| 설정: `features/settings/SettingsPage.tsx`, `useSettings.ts` | GET/PUT `/api/settings/`; UI 설정 및 환경변수/모델 설정 화면. S `web/routes/settingsroute.py`. | **부분 후보:** 언어·표시·입력 대기 UX 설정만 제품 설정과 통합. API 키/환경변수 객체를 통째로 제품 DB/프런트 DTO에 복제하지 않는다. |
| 로그인·현재 사용자: `features/auth/useAuth.ts` | GET `/api/auth/type`, `/login-url`, `/me`; S `web/auth`. `AUTOGENSTUDIO_AUTH_TYPE` 기본 `none`, manager에 NoAuth/guest 경로 존재. F의 user_id 파라미터는 서버 권한 자체가 아니다. | **새 경계 필요:** Editor 서버가 결정하는 로컬 단일 사용자 identity와 origin 정책. Studio 인증 provider 세트를 통째로 옮길 필요 없음. |
| 상태/버전·Deploy 화면: `features/deploy/DeployPage.tsx`, shared health hooks | GET `/api/health`, `/api/version` 호출. 화면의 endpoint 목록/배포 안내는 API 구현 증거가 아니다. 예: 안내의 PUT `/teams/{id}`와 실제 POST upsert가 다르다. | **우선 후보:** 실제 연결/버전 표시. 범용 배포 자동화는 이 조사에서 구현 확인 안 됨; 표시 문구만 보고 이전 범위로 잡지 않는다. |
| 대지 분석: `features/land/useLand.ts`, `shared/api/arrClient.ts` | `/arr/land/analyze/` POST, `/land/zones/`, `/land/stats/` GET을 호출. `/land/resolve/` POST 래퍼도 있지만 feature 호출은 이번 검색에서 확인 못함. Studio API가 아닌 별도 8000 대상이다. | **조건부 후보:** 현행 SiteContext/Law/ARR owner 기능과 데이터 계약을 먼저 대조. 이번에는 대응 서버 구현/실행을 확인하지 않았으므로 연결 완료로 표시하지 않는다. |

## 프런트 의존성이 확인되지 않은 백엔드 추가 기능

이 목록은 전체 AG 기능을 이전하자는 제안이 아니다.

- S의 `POST /api/a2a/import`, `GET /api/runs/{id}`, `GET /api/runs/{id}/messages`, HTTP MCP connect/status는 존재하지만 위 F 클라이언트의 대응 호출은 확인하지 못했다. 현재 UI에 없는 API까지 호환성을 약속하지 않는다.
- C의 `cohub_loader.py`는 협업 패턴 JSON을 AutoGen 팀 템플릿으로 변환/등록하는 도구다. `patterns/`, `templates/`, TypeScript `loader/`는 별도 자료이며, F의 HTTP 호출만으로 이 전체 기능이 사용된다고 볼 수 없다.
- C의 `sdk/client.py`는 Claude Agent SDK 단일/다중 턴, 컨텍스트, 도구 결과/사용량 수집을 제공한다. `model_factory.py`와 AutoGen provider 구성은 선택한 팀에 의해 간접 사용될 수 있으나 이번에는 실제 저장 팀 provider를 조사하거나 실행하지 않았다. 해당 SDK·인증·모델 비용·파일/명령 실행 권한을 기본 Editor 의존성으로 추가하지 않는다.
- `AG-cli/backend/main.py`는 Item CRUD 예제다. 조사한 F의 주 API 대상이라는 근거가 없으므로 제품 이전 후보에서 제외한다.
- S에는 SQLAlchemy/DB 관리, AutoGen component loading, 모델 provider, MCP SDK, 인증 provider 등이 연결된다. endpoint별 부분 추출 없이 Studio 전체를 import하면 선택하지 않은 런타임/초기화까지 따라온다. 특히 팀 목록 GET도 빈 DB에 기본 팀을 쓰므로 단순 조회를 무조건 무변경이라고 가정할 수 없다.

## 기존 Editor/Orchestrator가 이미 소유한 것

| 현재 코드 | 확인한 권위 / 재사용 방향 |
|---|---|
| E `backend/app/api/routes_planm_runs.py`, `backend/app/modules/planm_runs/service.py` | PLANM 생성·상태·대안·승인·발행 경로. Studio 팀 실행으로 대체할 이유가 없음. |
| E `backend/mcp/src/storage/sqlite-scene-store.ts`, `frontend/app/editor` scene API | scene 저장/재열기와 version 관리. Studio DB를 scene 저장소로 추가하지 않음. scene metadata의 projectId만으로 durable 제품 프로젝트/ACL이 구현되어 있다고 단정하지 않음. |
| O `orchestrator/graph.py` | 현재 Python `submit(project, branch, request_id, request)`, `queue_resume(run_id, supplied)`, `advance(run_id, resume=None)`가 존재. **Editor용 HTTP facade는 별도 구현 과제**다. 웹 요청에서 advance를 직접 실행하지 않음. |
| O `orchestrator/state.py` | create_run은 project/branch/request_id와 canonical request로 멱등 생성. run/runnable/queue_input 및 외부 call receipt를 저장. product DB가 이 owner DB를 직접 쓰거나 새 실행 큐를 만들지 않음. |
| O `orchestrator/state.py:events` | project/branch 이벤트 조회이지 재접속 가능한 완전한 run 스트림이라는 보장은 아님. 첫 화면은 owner run polling 가능; SSE/replay는 별도 owner 계약/테스트가 필요. |
| O `orchestrator/specialist_flow.py` | source revision 검사, args hash, owner request binding을 검증하는 read-only specialist 경로. 부분 결과·미확인 입력을 승인/수정 완료로 승격하지 않음. |

전 에이전트 표시의 근거는 [agent-connection-matrix.md](agent-connection-matrix.md)의 25개 catalog 항목이다. AG registry 행 수와 혼합하지 않는다. endpoint 선언, health 확인, adapter 지원, 입력 충족 여부를 별도로 표시해야 한다. `unsupported`, `not_connected`, `missing_input`을 성공처럼 채우지 않는다. PLANM/기존 MCP는 이 catalog를 임의로 늘리는 별도 행의 근거가 아니다.

## 선택을 위한 최소 묶음과 확인 과제

**우선 선택 후보**는 (1) 에이전트 목록/연결 상태, (2) 프로젝트별 요청/실행 이력과 결과, (3) owner가 요구한 추가 입력이다. AG-frontend의 이 화면 구성과 메시지 표시를 Editor UX에 추출할 수 있다. 해당 후보가 선택되면 Editor 제품 메타데이터와 owner HTTP facade를 작게 설계한다. 아직 SQLite 전체 스키마나 모든 기존 endpoint의 대체 DTO를 확정할 단계는 아니다.

팀 그래프 편집·갤러리·범용 MCP·외부 모델 설정·대지 분석은 위의 수요/중복/실제 서버 증거를 먼저 확인하는 별도 선택 항목이다. 자동으로 모두 다음 단계에 포함하지 않는다. Studio 상시 서버나 `/agentlab` 제품을 목표로 두지 않는다. 임시 어댑터가 꼭 필요해지는 경우에도 지원 endpoint, 종료 조건, 제거 테스트를 명시해야 하며 현재 조사만으로 도입을 권고하지 않는다.

선택 후 필요한 검증:

1. 프런트 API 래퍼와 실제 화면 소비 지점의 계약 테스트. 표시 전용 Deploy 목록을 구현으로 오인하지 않는 회귀 검사.
2. Editor에서 제출 → owner durable run ID → 상태/부분 결과 표시 → 새로고침 후 동일 실행 재조회. 같은 request ID의 중복 요청/응답 유실도 한 실행이어야 한다.
3. project/branch/source revision 불일치, owner timeout과 `external_outcome_unknown`, 지원하지 않는 cancel/agent에 대해 정직한 상태 표시. 입력 응답은 현재 interrupt에만 적용.
4. 제품 데이터와 scene store, owner run store를 독립 검증. 조회/상태 확인은 설계 geometry와 source revision을 변경하지 않아야 한다.
5. 서버가 결정한 사용자 identity와 허용 origin, 임의 URL/명령/provider 비노출, 설정/로그의 secret 비노출. 기존 guest user_id를 ACL로 재사용하지 않음.
6. 선택한 기능만으로 Editor를 기동·사용하고 Studio가 꺼진 상태에서도 통과하는 통합 테스트. 제거한 기능은 숨기거나 명확히 미지원 표시.

이번 변경은 이 문서 하나다. 설치·서비스 시작·제품 코드·원본 AG/AG-frontend 변경 및 동작 성공을 새로 주장하지 않는다.
