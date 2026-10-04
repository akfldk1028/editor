# Editor 중심 프론트엔드·백엔드 통합 설계

상태: 단계별 실행 중. 아래 최신 사용자 정정이 이전 통합 제안보다 우선한다. 실제 검증 범위는 migration 기록을 따른다.
연결 문서: [단계별 실행 계획](../superpowers/plans/2026-10-04-editor-platform-integration.md).

## 1. 목표와 범위

**최신 사용자 정정:** 최종 제품은 Editor 하나다. AG를 별도 제품/Studio 서비스로 계속 사용하지 않는다. 프론트 기준은 사용자가 의도적으로 가볍게 만든 `D:/Data/25_ACE/AG-frontend`다. 이 프론트의 실제 화면·기능·호출 API부터 조사하고 필요한 기능만 Editor 프론트와 백엔드로 순차 이전한다. AG의 모든 기능·라이브러리·백엔드를 넣는 계획이 아니다. 전체 에이전트 연결 요구와 AG 기능 전체 이식은 다르다.

기존 AG/Studio 코드는 이전 근거와 데이터 보존 대상이다. 별도 `/agentlab` 제품, 영구 Studio 서버, 영구 `/api/integrations/studio` 프록시를 목표 구조에 넣었던 제안은 철회한다. 원본 폴더 보존이나 Git 이력 리허설은 제품에 모든 소스를 포함한다는 뜻이 아니다. 기능별 채택·중복 통합·보류/제외 표가 실제 구현 범위를 결정한다.

2026-10-04 추가 사용자 확정: **AG는 Editor 제품에 기능적으로 통합되고 모든 에이전트는 Editor에 연결된다.** 폴더 동거 또는 별도 AG 콘솔 링크만으로 완료 판정하지 않는다. Editor의 기존 라우터에서 전체 에이전트의 발견·기능·호출·진행·필요 입력·결과 근거에 접근할 수 있어야 한다. 에이전트별 서버/소스 소유권 유지와 사용자 진입점 통합은 양립한다.

`D:/Data/25_ACE/editor`를 건축 설계 제품의 메인 저장소와 실행 진입점으로 삼는다. 사용자가 지정한 `AG-frontend`와 `AG`도 이 루트 안으로 이전한다. 프로젝트를 열고, 도면·3D를 편집하고, 에이전트 작업을 요청하고, 결과·근거를 비교한 뒤 명시적으로 반영하는 하나의 작업 흐름을 만든다.

단순 폴더 보존과 제품 통합은 별도 단계다. 기존 데이터·Git 이력·미커밋 연구 결과를 보존하고, 현재 ARR·Orchestrator·전문 에이전트의 책임을 유지하면서 선별한 기능부터 옮긴다. 초기 설계 커밋은 완료됐고, 현재는 기능 조사·선별과 단계별 구현/검증을 진행한다.

## 2. 확인한 현재 상태

| 위치 | 실제 역할과 Git 상태 | 설계 영향 |
|---|---|---|
| `editor` | 독립 Git, 기준 HEAD `bdc6ed38`, 조사 시작 시 clean | 계획 커밋의 기준 저장소 |
| `AG-frontend` | 상위 `D:/Data/25_ACE` Git 소속, 해당 경로 tracked233개, 조사 시 경로 한정 clean; 상위 HEAD `3f372a90` | 독립 저장소인 것처럼 `.git`을 이동하면 안 됨 |
| `AG` | 독립 Git HEAD `179fe496`, tracked 수정과 untracked 연구 결과 존재 | Git bundle만으로 미커밋·ignored 결과를 보존할 수 없음 |
| `agents/OrchestratorAgent` | 별도 Git, 중앙 최근 커밋 `4fd9f2c` | 실행 상태·요청 바인딩·A2A의 기존 책임 유지 |

소스 근거:

- `frontend/app/editor/package.json`: Next.js 편집 앱, React19, Pascal core/viewer/editor 조합. 현재 lockfile을 기준으로 하며 버전 업그레이드는 별도 작업이다.
- `frontend/app/planm`: 이미 존재하는 Vite 제품 셸. `infra/dev/runtime.mjs`는 셸5173, Next3002(`/editor`), FastAPI8000, MCP3917, DWG4317을 조합한다.
- `../AG-frontend/vite.config.ts`: 동일5173 사용, `/api`를 AutoGen Studio8081로, `/arr`를8000으로 전달한다. 현재 editor 셸은 `/api/v1`과 DWG `/api`를 사용하므로 그대로 합칠 수 없다.
- `backend/app/main.py`, `api/routes_planm_runs.py`, `api/routes_pascal.py`: 기존 FastAPI PLANM 실행·승인·Pascal 연계가 있다. 새 백엔드를 처음부터 중복 생성하지 않는다.
- `../AG-frontend/src/shared/api/client.ts`: Studio 응답 envelope와 localStorage 사용자/token에 의존한다. 이것을 제품 사용자 권한의 근거로 사용할 수 없다.
- `AG/autogen_a2a_kit/AG_Cohub`는 협업 패턴/SDK 라이브러리다. 실제 Studio 서버와 그 API를 대신하는 제품 백엔드로 간주하지 않는다.
- `docs/PLAN-README.md`, `backend/app/core/planm_location.py`: PLANM은 최근 공유 `../agents/planm`으로 분리됐다. 이번 통합에서 다시 복제하지 않는다. Editor 내부의 기존 engine 연결은 조사 대상이며, 중앙 Orchestrator의 실시간 PLANM 연결 완료를 의미하지 않는다.

문서 일부에는 과거 `agents/planm` 트리가 남아 있다. 실행 전 현재 코드와 구조 테스트를 기준으로 정리한다. 문서에 적힌 과거 테스트 개수를 이번 실행 결과로 인용하지 않는다.

## 3. 접근 방식과 선택

| 방식 | 장점 | 문제 |
|---|---|---|
| 폴더만 한곳에 이동 | 빠른 경로 정리 | 포트·API·사용자·프로젝트·실행 권한 충돌 유지 |
| 모든 기능을 새 앱으로 재작성 | 표면적으로 단일 구조 | 기존 편집기·실행 근거·연구 결과를 대체하는 비용이 큼 |
| **보존 이전 후 기능별 통합** | 기존 자산과 검증 경로 유지, 단계별 되돌리기 가능 | 전환 기간에 독립 앱/서비스를 명시적으로 관리해야 함 |

세 번째 방식으로 진행한다. 2026-10-04 사용자 지시에 따라 프론트 통합은 **기존 라우터에 경로를 추가**한다. 기존 PLANM 셸의 `/dwg`, `/planm`, `/editor`와 Next 편집기의 scene 경로를 보존한다. 제품 셸에 `/projects`, `/projects/:projectId`, `/agents`, `/runs/:runId`를 추가하고, 편집 화면으로의 연결은 명시적인 project/scene ID로 한다. Next로 전체 셸을 교체하거나 AG root router를 중첩하지 않는다.

## 4. 디렉터리와 소유권

```text
editor/
  AG-frontend/                 이전한 기존 Vite 앱; 통합 전 비교 기준
  AG/                          기존 AG 이력·소스·연구 자료 보존 영역
  frontend/app/editor/         기존 Next 편집 도구와 scene 경로 유지
  frontend/app/planm/          기존 제품 셸에 프로젝트·에이전트 라우트 추가
  frontend/components/viewer/  editor-agnostic 3D 렌더링
  frontend/components/editor/ 재사용 편집 컴포넌트
  frontend/elements/           기존 UI·노드 요소
  backend/app/api/             제품 HTTP 경계
  backend/app/modules/        프로젝트·산출물·작업 조회/명령 전달
  backend/app/adapters/        Orchestrator·PLANM·DWG 등 실제 owner 계약 어댑터
  backend/mcp/                 기존 scene 저장·MCP 경계
  resources/lib/core/          순수 scene 데이터/로직; HTTP·Three.js·작업 UI 금지
  resources/lib/platform-contracts/  새 공개 DTO/client 계약 패키지(구현 예정)
  infra/dev/                   제품 서비스 manifest·상태 확인·기동
  infra/docker/                경로가 분리된 reverse proxy와 배포 설정
  docs/                        설계, 결정, 이전 manifest
```

`AG/`, `AG-frontend/`는 필요시 소스 대조를 위한 보존 경계이며 실제 제품 소스와 별개다. 기능 조사 전에 전체 AG를 제품 경로에 자동 import하지 않는다. root workspace glob을 확장하지 않는다. 선별한 기능의 의존성만 검토해 사용하고, 연구 데이터·vendor checkout·가상환경·결과 디렉터리를 빌드/배포하지 않는다.

기능 이식 시 AG UI는 `frontend/app/planm/src/features/agent-workspace/`로, 재사용 DTO는 `resources/lib/platform-contracts/`로 들어간다. AG 백엔드 통째 복사나 core/viewer에 UI 의존성을 추가하는 방식은 금지한다. 이전 완료 뒤에도 원본 역할을 가진 AG 패키지와 연구 자료는 editor 아래 보존할 수 있지만, 제품 실행 권한은 한 곳만 갖는다.

## 5. 제품 데이터와 실행의 책임

| 데이터/명령 | 권위 있는 소유자 | 다른 계층의 역할 |
|---|---|---|
| 사용자·workspace·project 및 접근권한 | 제품 Backend | UI는 표시·명령 입력 |
| scene 그래프와 저장 revision | 기존 scene/MCP 저장 경계 | 제품 DB는 scene ID/revision 참조; 그래프 이중 저장 금지 |
| 건축 작업 상태·재시도·원천 버전·A2A receipt | Orchestrator | 제품 API는 전달·조회·projection, 새 작업 엔진 금지 |
| PLANM 자체 단계/승인/산출물 | 기존 PlanmRunService 및 PLANM 계약 | 중앙 작업과 provider_run_id로 대응, status 임의 승격 금지 |
| 형상·법규·설비·인테리어 판단 | 각 전문 에이전트/ARR | Editor는 owner 근거를 표시 |
| 선별한 팀 구성·세션·에이전트 설정 기능 | Editor Backend의 해당 기능 모듈 | 기존 AG 데이터 형식을 조사해 필요한 데이터만 명시적으로 이전; Studio 서버에 영구 의존하지 않음 |

제품 Project와 Scene와 Orchestrator project/branch는 명시적 ID 매핑을 갖는다. 이메일·폴더명·현재 화면 제목으로 조인하지 않는다. 새 프로젝트 registry는 지속 저장한다. MCP의 임시 project placeholder나 브라우저 localStorage를 제품 DB로 쓰지 않는다.

제품 메타데이터는 기존 저장 기술과 별도 namespace의 SQLite로 시작하는 안을 제안한다. migration/version/backup/concurrency 테스트를 붙이고, 다중 서버 배포 전 DB 선택을 별도 ADR로 확정한다. 기존 SQLite/JSON 실행 데이터를 한 DB에 강제 병합하지 않는다.

## 6. API와 보안 경계

제품용 새 namespace는 `/api/v1/platform`이다. 기존 `/api/v1/planm`, Pascal 경로와 DWG 경로는 첫 단계에서 유지한다. AG-frontend가 실제 사용하는 API 중 채택한 기능의 계약을 Editor Backend로 이전한다. Studio 전체 API나 `/api/integrations/studio` 프록시를 기본 제품 의존성으로 추가하지 않는다. 임시 전환 adapter가 필요하면 대상 기능·제거 기준·기간을 따로 명시한다.

제안 계약(모두 신규, 현재 존재한다고 가정하지 않음):

- `GET/POST /api/v1/platform/projects`, `GET /projects/{project_id}`.
- `POST /projects/{project_id}/runs`: `Idempotency-Key`, branch_id, intent, source_versions, provider를 받는다. 서버가 사용자와 프로젝트 권한을 검증한다.
- `GET /runs/{run_id}`: transport_state와 owner outcome/partial/blocked를 구분한다.
- `GET /runs/{run_id}/events`: 지속 event_id와 재접속 cursor를 가진 SSE. 기존 AG의 화면·스트리밍 표현은 재사용 후보지만 Studio 실행 프로토콜을 새 제품의 영구 계약으로 복제하지 않는다.
- `GET /artifacts/{artifact_id}`: 프로젝트 권한·종류·SHA256 검증 후 전달한다. 브라우저에 Windows 경로나 임의 파일 읽기 API를 노출하지 않는다.
- `POST /projects/{project_id}/proposals/{proposal_id}/apply`: source revision과 선택 revision, 명시적 사용자 의도를 검증한 후 owner 권한 안에서만 반영한다. 진단 proxy는 accepted room으로 승격할 수 없다.

Orchestrator에 이 API를 직접 있다고 가정하지 않는다. 별도 owner 작업으로 안정적인 서비스 경계를 추가하고 제품 adapter가 사용한다. Backend가 Orchestrator SQLite 파일을 직접 수정하거나 프로세스를 request마다 임의 실행하지 않는다.

인증은 서버가 발급/검증하는 세션과 프로젝트 권한을 기준으로 한다. 로컬 개발은 명시적 loopback 단일 사용자 모드를 둘 수 있지만 운영 인증과 혼동하지 않는다. 상태 변경은 CSRF/origin 정책, artifact 접근은 경로 이탈과 다른 프로젝트 ID 접근 테스트가 필요하다. 기존 서비스 token은 브라우저 번들에 넣지 않는다.

## 7. 화면과 사용자 흐름

프로젝트 목록 → 프로젝트 작업 공간 → 도면/3D → 에이전트 요청 → 진행·누락 입력 → 결과 비교 → 명시적 적용으로 이어진다. 선택된 project/branch/source revision은 도면, 3D, 결과 패널이 공유한다.

먼저 AG-frontend의 실제 라우터와 호출 지점을 조사한다. Team Builder·Gallery·MCP/Agent 관리 등의 이름만 보고 전체 이식을 결정하지 않는다. 화면별 쓰임, Editor 중복 기능, 실제 백엔드 의존성, 추가 무게를 비교해 채택 대상을 정한다. 최초 제안인 Interior 결과의 원본 보존 조회·비교도 이 선별표와 연결한다. 이후 선택된 요청·진행·결과 흐름을 하나씩 검증한다.

scene 원본, owner proposal, 선택된 설계, diagnostic-only 자료를 구분한다. 현재 Interior 패널, gross 공간 배분, Systems blocked를 완성된 설계로 표시하지 않는다. 서비스 연결 성공과 도메인 완료를 별도 표시한다.

## 8. Git·데이터 이전 원칙

이전 전 editor/AG/상위 저장소의 commit·index·dirty 상태와 대상 경로의 전체 파일 manifest를 만든다. tracked/untracked/ignored를 구분하고, reparse point의 실제 경로를 기록한다. Git bundle은 이력, 별도 파일 snapshot은 미커밋·ignored 데이터를 보존한다. 자격증명은 소스 커밋과 공개 manifest에 넣지 않는다.

권장 이력 정책: AG는 임시 clone에서 이력을 prefix `AG/`로 가져오는 subtree 방식, AG-frontend는 상위 저장소의 해당 경로만 임시 clone에서 분리해 `AG-frontend/`로 import한다. 소스 저장소에 filter/rewrite를 실행하지 않는다. `.git` 삭제나 우연한 gitlink 생성으로 해결하지 않는다.

AG의 dirty overlay와 연구 결과는 별도로 복사·검증하고, 실행에 필요한 변경만 검토 후 커밋한다. 제외된 파일도 snapshot/이전 대상에 남는다. 거대한 결과나 민감 파일을 무조건 새 저장소에 stage하지 않는다. 이력 크기 때문에 subtree가 부적합하면 실행 전에 ADR로 대안을 선택한다.

전환은 **복사 → 파일 해시/개수/이력 검사 → 새 경로 실행 → 실제 UI/API 검증 → 설정 cutover** 순서다. 기존 위치 삭제는 별도 후속 작업이다. rollback 기간 동안 원본은 보존하고, 제품 소스의 이중 편집은 금지한다.

## 9. 완료 기준과 이번 범위

전체 에이전트 연결표를 source registry/owner manifest에서 작성한다. 각 행에 agent ID, capability, 실제 서비스 경계, Editor 경로, adapter, 호출 task ID, source binding, 결과 표시, 상태(verified/blocked/unavailable/unimplemented)를 기록한다. 목록에 보이기만 하는 것은 연결 완료가 아니다. 미완성 owner도 숨기지 않고 부족한 계약/입력을 표시한다. 편집 가능한 제품 설정과 조회 전용 owner registry를 구분하며 중복 권위 저장소를 만들지 않는다.

통합 완료에는 이전 데이터 보존, 충돌 없는 단일 진입점, 저장 후 재시작 복원, 프로젝트 격리, 중복 없는 작업 제출, SSE 재연결, stale 결과 거부, 원본/결과 비교, rollback 증거가 모두 필요하다. 실제 프로젝트의 도면·주차·3D와 전문 에이전트 결과를 함께 검증한다.

완료 판단에는 Editor가 선별한 기능을 직접 제공하고 해당 기능에 기존 AG 실행이 필요 없다는 증거가 포함된다. 원본 보존·기존 앱 테스트 성공·목록 표시만으로 제품 통합을 완료 처리하지 않는다. 현재 단계의 실행 증거와 남은 작업은 migration 기록과 담당 메모리에 별도로 남긴다.
