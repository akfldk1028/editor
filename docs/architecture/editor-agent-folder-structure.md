# Editor 에이전트 통합 폴더 구조

> 2026-10-04 후속 사용자 지시: 최종 구조는 [Editor·ARR·AG 통합 설계](2026-10-04-unified-editor-arr-ag.md)를 따른다. 아래 외부 owner 소스 영구 유지 결정은 변경되었다. ARR·AG 및 전문 owner의 필요한 소스·기능을 Editor 안으로 이전하고, 원본 경로 없이 운영하는 것이 새 목표다. 아래 내용은 초기 이식 단계의 기록이다.

2026-10-04. 경량 AG-frontend의 선별 이식에 적용하는 구조 결정. 기존 통합 설계의 `editor/AG`, `editor/AG-frontend` 전체 보존 트리와 신규 공용 계약 패키지 제안보다 이 문서가 우선한다. 아래 신규 경로는 구현 예정이며 현재 존재하거나 연결 완료됐다는 뜻이 아니다.

## 제품 구조

```text
D:/Data/25_ACE/editor/
  frontend/
    app/
      planm/                         기존 Vite 제품 진입점; 지금은 이름 유지
        src/
          app/
            App.tsx                  기존 내비게이션에 경로 추가
            routes.ts                경로 해석; 기능 구현을 넣지 않음
          features/
            planm-planning/          기존 PLANM 화면
            agent-workspace/
              agents/                목록·기능·연결 상태
              projects/              프로젝트 선택·owner/scene 연결
              runs/                  요청·진행·추가 입력·이력·결과
              api/                   Editor API client·공개 DTO
              components/            위 세 화면이 함께 쓰는 작은 UI
          integrations/dwg/          기존 DWG 연결
      editor/                        기존 Next 2D/3D 편집 앱·scene 경로
    components/viewer/               독립 3D 렌더링; 에이전트 API 금지
    components/editor/               기존 재사용 편집 UI
    elements/                        기존 공용 UI
  backend/
    app/
      api/routes_platform.py         /api/v1/platform HTTP 경계
      schemas/platform.py            요청·응답 DTO; owner 내부 객체 비노출
      modules/platform/
        projects.py                  project/branch/scene 연결 검증
        repository.py                제품 메타데이터 SQLite
        runs.py                      제출·조회·입력 전달; 실행 큐 아님
        artifacts.py                 허용된 결과 조회·hash/source 검증
      adapters/orchestrator.py       owner HTTP client; 타임아웃·오류 변환
      main.py                        기존 앱에 router 등록
    tests/test_platform_*.py         제품 API·격리·멱등·오류 계약
    mcp/                             기존 scene 저장소; 그래프 이중 저장 금지
  resources/lib/core/                순수 scene 로직; 제품 통합 코드 금지
  infra/
    dev/                             기존 서비스 기동·설정 확장
    e2e/                             기존 화면 회귀 + 실제 통합 검증
    migration/                       원본 보존·hash·출처 확인 도구
  docs/
    architecture/                    구조·책임 결정
    integrations/                    기능 선별표·연결 증거
    migrations/                      원본 → 대상 파일 대응표
    superpowers/plans/               단계별 실행 계획
```

## 외부 저장소와 데이터

- `D:/Data/25_ACE/AG-frontend`: 사용자 경량 프론트 원본. 기능별로 복사·수정·검증하고 원본을 삭제하지 않는다. 새 제품에서 이 경로를 import하거나 두 번째 Vite 서버를 띄우지 않는다.
- `D:/Data/25_ACE/AG`: 필요한 구현을 조사하는 원본·연구 자료. 제품 루트에 통째로 넣거나 Studio를 상시 실행하지 않는다. 전체 이력은 보호된 백업으로 보존한다.
- `D:/Data/25_ACE/agents/<owner>`: Orchestrator·PLANM·전문 에이전트의 소스와 메모리. Editor는 서비스 계약으로 연결하며 소스를 복제하지 않는다.
- 제품 DB·로그·실행 결과는 명시적으로 설정한 Git 외부 데이터 경로에 둔다. snapshot·venv·node_modules·모델·대형 연구 결과를 제품 소스 트리에 이식하지 않는다.

## 의존성과 이전 기준

1. `app → features/agent-workspace → api → Editor Backend → Orchestrator → 전문 owner` 순서다. 브라우저가 owner DB나 임의 서비스 URL에 접근하지 않는다.
2. AG의 `features/agents`는 `agent-workspace/agents`, `playground`와 `history`의 채택 부분은 `agent-workspace/runs`로 옮긴다. AG의 root router·provider·전역 CSS·lockfile을 통째로 덮어쓰지 않는다.
3. 1차에는 API DTO를 해당 기능의 `api/`에 둔다. 공용 계약 패키지는 두 번째 실제 소비자가 생길 때 추출한다. 빈 패키지·미사용 폴더는 미리 만들지 않는다.
4. 기존 `planm` 폴더를 `platform`으로 바꾸는 작업은 통합과 분리한다. 현재 경로에 의존하는 dev·proxy·E2E 설정을 먼저 유지한다.
5. 이전 파일마다 원본 경로·원본 commit·이전 시 SHA256·대상 경로·수정 이유·검증 명령을 `docs/migrations/ag-selected-source-map.json`에 기록한다. 기존 파일 충돌은 덮어쓰지 않고 diff로 해결한다.
6. 기능별 CSS 범위를 제한하고 페이지를 lazy-load한다. 첫 단계에 React Flow·DND·AutoGen·범용 MCP 의존성을 추가하지 않는다. 기존 Editor dependency/lockfile을 기준으로 필요한 의존성만 추가한다.

## 첫 통합 범위

| 순서 | 채택 | 경로 | 완료 기준 |
|---|---|---|---|
| 1 | 에이전트 목록·기능·상태 | `/agents` | 중앙 catalog 표시; 선언/health/실제 호출 검증을 구분 |
| 2 | 프로젝트 연결 | `/projects`, `/projects/:projectId` | 새로고침·재시작 후 project/branch/scene 연결 유지 |
| 3 | 작업 요청·진행·추가 입력·이력·결과 | `/runs/:runId`, 프로젝트 내부 실행 목록 | owner durable run과 실제 receipt를 표시; 중복 제출 방지 |

팀 빌더·갤러리·범용 MCP 관리·배포·예약·Flow 팝업은 1차에서 제외한다. 대지 분석은 기존 PLANM/DWG와 기능 중복을 확인한 뒤 별도로 결정한다. 결과 조회와 geometry 적용은 분리하며, 설계 적용은 후속 기존 승인 계획을 따른다.
