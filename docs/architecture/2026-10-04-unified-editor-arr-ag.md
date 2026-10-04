# Editor · ARR · AG · Agents 통합 제품 설계

2026-10-04. 상태: 사용자 요청에 따른 목표 설계. 소스 이동·운영 전환은 아직 수행하지 않았다.

## 목표와 이전 결정 변경

최종 제품 루트는 `D:/Data/25_ACE/editor` 하나다. ARR를 외부 API로 연결하는 현재 방식은 이전 과정의 임시 상태다. ARR 소스·프론트 기능·실행 설정과 전문 에이전트 소스까지 Editor에서 관리한다. 사용자는 한 주소에서 같은 프로젝트의 대지·법규·설계·주차·도면·3D·에이전트 작업을 사용한다.

사용자 재확인: 통합 후 **별도 ARR·AG·AG-frontend 프로젝트는 운영에 필요 없어야 한다.** 원래 경로를 실행하거나 원래 저장소에서 소스를 읽는 구성이 남으면 이전 미완료다. 아래 `backend/arr`라는 이름은 Editor가 소유하는 내부 모듈의 출처를 나타내며, 외부 ARR 제품을 유지한다는 뜻이 아니다. 최종 운영·수정·테스트·배포는 모두 Editor에서 수행한다.

이 문서는 `editor-agent-folder-structure.md`의 **owner 소스를 영구적으로 외부에 둔다**는 결정과 경량 UI만 통합 대상으로 삼던 범위를 변경한다. 기존 모듈 경계, 원본 보존, 검증 후 전환 원칙은 유지한다. `AG-frontend`뿐 아니라 `ARR/frontend`도 별도 원본으로 조사·이식한다. “모든 기능”은 전수 목록과 대응표로 관리하며, 이전 계획에서 보류한 메뉴를 임의로 삭제하거나 완료 처리하지 않는다.

하나의 제품·저장소·프로젝트 체계·기동 명령을 만든다. Python/Node/Django/FastAPI/A2A 프로세스는 책임과 의존성에 따라 같은 제품의 내부 서비스로 구동한다. 통합과 동시에 Django를 전부 FastAPI로 재작성하거나 모든 가상환경을 합치지 않는다.

## 현재 확인한 실제 구조

- Editor: Vite `frontend/app/planm`, Next `frontend/app/editor`, FastAPI `backend/app`, scene 저장/MCP `backend/mcp`, 독립 core/viewer.
- ARR: Django `backend/backend/urls.py`에 land/law/design/admin 연결. design에 작업 생성·실행·취소·스트림·결과·근거, 대화형 수정, 매스/BOOK/포트폴리오, 배치 operations, 평면과 입면 산출물 경로가 있다.
- ARR 프론트: `frontend/src/routers/index.tsx`에 LawChat, LandMap, DesignPage, BookLanguagePage, 이력, 로그인·설정 경로. React18/Three0.180/Electron 구성이며 Editor React19/Three0.185와 별도이므로 root lockfile을 합치지 않는다. 현재 ARR build 스크립트에는 배포 옵션이 포함되어 있어 기준 검증 시 자동 실행하지 않는다.
- ARR parser/graph_db/gemini/agents 코드는 존재하지만 위 기본 Django URL 또는 installed-app 설정에서 일부 비활성이다. 별도 서비스·프론트 호출까지 조사하기 전 “사용 안 함”이나 “동작 완료”로 판정하지 않는다.
- AG-frontend: 작업 입력·실행·이력·팀·MCP·갤러리·설정 등. 원본의 disabled Gallery 생성과 미연결 scheduler는 동작 완료 기능이 아니다.
- 현재 구현한 `/land`는 PNU 조회·표시 일부, `/runs`는 health 실행 일부다. ARR/AG 전체 흡수 완료가 아니다. 원본 D: Editor의 Gitagent build artifact 누락도 먼저 복구해야 한다.

## 최종 폴더 구조

아래는 목표 경로이며 미구현 빈 폴더를 미리 생성하지 않는다. `workbench` 이름 변경은 기능 이전과 분리한 마지막 단계다.

```text
editor/
  frontend/
    app/
      workbench/                  현재 planm; 전체 제품 진입점
        src/app/                  라우터·제품 내비게이션·프로젝트 context
        src/features/
          projects/               프로젝트 선택·설정·산출물 연결
          land-analysis/          주소/PNU·지도·지형·규제선
          law/                    법령 검색·원문·법규 검토
          program/                요구사항·용도·면적 프로그램
          massing/                매스·BOOK 언어·대안 비교
          masterplan/             대지 배치·접근·동선
          parking/                주차·램프·차량 동선
          planm-planning/         기존 평면 계획
          elevation/             입면·렌더·검토
          systems/               구조·설비 검토
          interior/              이미지·재료·3D 적용
          remodeling/            기존 상태·리모델링
          agent-workspace/       실행·메시지·추가 입력·이력·흐름
          settings/              인증·표시·모델·허용 도구 설정
        src/integrations/dwg/     기존 DWG 기능
      editor/                    기존 Next 2D/3D 편집 경험
      ifc-converter/             기존 변환 앱
    components/{viewer,editor}/  기존 독립 렌더링/편집 컴포넌트
    elements/                    기존 공용 UI·노드
  backend/
    app/                         제품 API(FastAPI), 유일한 공개 업무 API
      api/                       기능별 /api/v1 경계
      schemas/                   제품 DTO
      modules/                   프로젝트·실행 연결·산출물·적용 작업
      adapters/                  같은 제품 내부 domain/agent 호출
    arr/                         ARR Django 서비스의 새 소스 소유 위치
      manage.py
      backend/                   Django settings/urls/asgi, 기존 package 유지
      {core,land,law,design}/     기존 앱·모델·마이그레이션·도메인 엔진
      {src,config}/              실제 import되는 지원 코드
      tests/                     이전 후 경로·계약·회귀 검증
    mcp/                         기존 scene 저장·MCP, scene 단일 쓰기 책임
    {cli,ifc-converter}/         기존 서비스
  agents/
    OrchestratorAgent/           실행 조정·worker·메모리
    planm/                      평면 owner; 원본 이름 유지
    <기존 Agent 디렉터리명>/      전문 구현·tests·memory·agent manifest
    {a2a,a2a_common}/            현재 공용 통신 소스, 검증 후 정리
    docs/                       공통 에이전트 계약·handoff
    skills/                     Editor 기존 개발 스킬, 전문 owner와 구분
  resources/
    lib/core/                   scene 순수 로직, ARR 계산 코드 유입 금지
    <기존 자산 및 검증된 신규 자산>/
  infra/
    dev/                        한 번에 기동·상태·종료; Windows 숨김 실행
    config/services.json        모든 내부 서비스 경로·역할·health·데이터 참조
    docker/                     Neo4j 등 필요한 의존 서비스 정의
    migration/                  inventory·복사·hash·DB 이전·rollback 도구
    e2e/                        기능별 이전 동등성 및 전체 제품 시나리오
  docs/
    architecture/               책임·데이터·계약 설계
    migrations/                 전수 대응표·cutover 기록
    integrations/               실제 검증 근거
    superpowers/plans/          실행 계획
```

`backend/arr`는 원래 ARR 경로를 영구 참조하는 링크가 아니라 새 소스 소유 위치다. `backend/arr/backend`와 Editor의 `backend` Python namespace 충돌을 피하도록 Django는 별도 환경·cwd·엔트리로 실행한다. FastAPI에서 Django의 `backend.*`를 직접 import하지 않는다. 기존 Django migration app label을 소스 이동 과정에서 바꾸지 않는다.

주차 엔진 등은 우선 원래 ARR package 내부에서 작동시킨다. 기능 이름과 폴더를 맞추기 위한 대규모 내부 재배치는 동등성 검증 뒤 별도 작업이다. 공통 계약 패키지는 실제 공유 소비자가 생길 때만 추출한다.

## 원본 → 목적지 및 기능 책임

| 원본 | 최종 위치·처리 | 검증할 사용자 동작 |
|---|---|---|
| ARR/backend의 활성 Django 앱·실제 지원 import | backend/arr | 대지·법규·설계 API와 기존 계산 동일성 |
| ARR/frontend/src/land | features/land-analysis | 지도 선택·주소/PNU·표고·경계·규제선 |
| ARR/frontend/src/law | features/law | 검색·스트리밍·원문·분야·오류 |
| ARR/frontend/src/design | massing/masterplan/parking/elevation 및 scene adapter | BOOK·매스 생성/수정·대안·배치·주차·입면·근거 |
| ARR 프론트 이력·계정·설정 | projects/agent-workspace/settings | 기존 데이터 열기·설정 저장·권한 |
| AG-frontend | 대응 기능별 경량 UI | 입력·첨부·중단/재개·이력·비교·내보내기·팀/MCP/갤러리 등 전수 대응 |
| AG backend 중 실제 사용 기능 | 제품 modules/agents 또는 필요한 소유 모듈 | Studio 없이 동작; 불필요한 중복 실행 엔진 신설 금지 |
| 외부 agents/<이름> | editor/agents/<같은 이름> | 실제 A2A 요청·receipt·재시작·owner 기억/지침 |
| 비활성 legacy·실험·연구 | 백업·별도 보존 자료와 명시적 backlog | 사용 경로 전수 조사; 제외 결정 없이 기능 목록에서 지우지 않음 |

모든 활성 사용자 동작은 `이식`, `동등 기능으로 대체`, `미구현/막힘` 중 하나와 검증 근거를 갖는다. 중복 화면은 하나로 합치되 입력·결과·저장 기능을 빠뜨리지 않는다. 비활성 기능을 제품에 자동 활성화하지 않으며 복원 필요 여부를 별도 기록한다.

## 프로젝트·실행·데이터

- Editor `project_id`를 제품 기준으로 사용한다. 기존 `owner_project_id`, `branch_id`, `scene_id/revision`, ARR `job_id/design_id/analysis reference`는 namespace를 포함한 연결표로 관리한다. 같은 문자열을 같은 객체로 가정하지 않는다.
- 제품 DB: 프로젝트·사용자 권한·외부 ID 대응·산출물 참조. Django DB: ARR 분석/설계 기록. Orchestrator store: 실행·checkpoint·receipt. Scene store: 편집 가능한 그래프. Neo4j/vector 저장소: 기존 검색 자료. 각 데이터는 한 소유자만 쓰며, 물리 DB 병합은 이번 이전의 선행 조건이 아니다.
- 런타임의 목표 위치는 Git 외부 `D:/Data/25_ACE/runtime/editor/{product,arr,agents,scenes,artifacts,logs}`다. SQLite는 온라인 backup API 또는 쓰기 중단 후 일관된 snapshot으로 옮긴다. WAL 파일을 무시한 생파일 복사는 금지한다. Neo4j와 파일 artifact도 각각 복원 검증한다.
- 긴 작업은 Orchestrator가 조정하고 ARR의 기존 job ID를 연결한다. 한 사용자 요청에서 두 실행기가 같은 계산을 중복 시작하지 않는다. 실행 취소·추가 입력·재시도는 owner가 실제 지원하는 계약으로 검증한다.
- 산출물 → 3D 적용은 입력 revision/hash·좌표계·단위·층 기준을 검증하고, 같은 artifact를 재적용해도 중복 객체가 생기지 않아야 한다. DWG·주차·입면·인테리어 모두 scene 단일 쓰기 경계를 사용한다.
- Systems/DomainExpert/InteriorDesign의 partial/blocked는 제품 화면에도 유지한다. 폴더 이전이 전문 기능 완성을 뜻하지 않는다.

## 화면·운영

프로젝트 화면은 대지 → 법규 → 프로그램 → 매스 → 배치/주차 → 평면 → 입면/실내/설비 → 검토 흐름으로 연결한다. `/projects/:projectId/<feature>`에서 같은 context를 사용한다. 기존 `/dwg`, `/planm`, `/editor`, `/land`, `/agents`, `/runs/:id`와 scene 링크는 초기 이식 동안 보존하고, 이후에도 유효한 진입 또는 명시적 프로젝트 선택으로 연결한다.

최종 사용자 주소는 하나다. workbench가 UI 진입점, Next editor는 같은 origin의 `/editor`, FastAPI는 `/api/v1`을 담당한다. Django·worker·A2A·MCP 포트는 내부 서비스다. `infra/dev/product.mjs`와 services registry에서 Editor 내부 경로로 시작한다. 중간 이전에는 원본/신규 중 한 경로만 선택하고 서로 다른 DB의 건강한 프로세스를 잘못 재사용하지 않도록 config identity를 검증한다.

## 전체 완료 기준

1. 전수 기능표의 모든 활성 동작에 이식 또는 동등 대체와 통과 근거가 있다. 미완성은 0건 또는 별도 합의된 잔여 범위로 명시한다.
2. 새 checkout+명시적 데이터 복원으로 재현 가능하다. 예전 ARR/AG/AG-frontend/agents 소스 경로를 실행·import·자산·메모리가 참조하지 않는다.
3. 기존 DB·설계·도면·주차·3D 결과를 열고 수정·저장·재열기·실패 복구까지 검증한다.
4. 숨김 기동·종료·재부팅 복구·로그·백업·rollback이 하나의 제품 운영 기록으로 제공된다.
5. 원본 삭제는 완료 기준이 아니다. 보호된 원본·이력·snapshot을 보존한 상태로 새 제품만 운영할 수 있어야 한다.
