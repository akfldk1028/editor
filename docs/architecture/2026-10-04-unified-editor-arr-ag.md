# Editor · ARR · AG · Agents 통합 제품 설계

2026-10-04. 상태: 기능별 통합 진행 중. 용도지역 목록의 Editor 소유 모듈 이전을 검증했다. 전체 소스 이전·운영 전환은 미완료다.

## 목표와 이전 결정 변경

최종 제품 루트는 `D:/Data/25_ACE/editor`다. ARR·AG 제품 소스·프론트 기능·실행 설정은 Editor에서 관리한다. **공용 에이전트 소스·환경·메모리·실행 상태는 `D:/Data/25_ACE/agents`에 유지**하고 Editor 및 다른 제품이 API/A2A로 사용한다. 사용자는 Editor에서 같은 프로젝트의 대지·법규·설계·주차·도면·3D·에이전트 작업을 사용한다.

사용자 재확인: 통합 후 **별도 ARR·AG·AG-frontend 프로젝트는 운영에 필요 없어야 한다.** 원래 경로를 실행하거나 원래 저장소에서 소스를 읽는 구성이 남으면 이전 미완료다. 최신 정정에 따라 `backend/arr`로 원본 트리를 통째로 옮기는 안은 폐기한다. 기존 `backend/app/modules`에 기능별로 통합하며, 상세 책임은 [기능별 백엔드 통합](2026-10-04-backend-domain-integration.md)을 따른다.

최신 사용자 정정: 앞서 작성한 owner 소스의 Editor 내부 이전 결정은 철회한다. 외부 공용 agents는 정상 의존성이며 ARR·AG 원본 제거 기준의 예외다. 에이전트의 운영·수정·테스트·배포는 공용 owner에서 독립 관리한다. `AG-frontend`뿐 아니라 `ARR/frontend`도 조사·이식한다. “모든 기능”은 전수 목록과 대응표로 관리한다.

Editor 제품의 저장소·프로젝트 체계·기동 명령을 통합한다. Python/Node/Django/FastAPI 제품 프로세스는 내부 서비스로 구동하고 공용 worker/A2A는 독립 서비스로 연결한다. 통합과 동시에 Django를 전부 FastAPI로 재작성하거나 모든 가상환경을 합치지 않는다.

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
      modules/                   기존 계산 모듈과 기능별 서비스·저장
        platform/                프로젝트·실행 연결·산출물·적용 작업
        land/                    대지·주소·지형·지도
        regulations/             법규 자료·검색·판정
        {massing,masterplan,parking,elevation}/  검증된 기능 단위로 생성
      adapters/                  내부 domain 및 외부 공용 agent 호출
    tests/                       기능별 이전·계약·회귀 검증
    mcp/                         기존 scene 저장·MCP, scene 단일 쓰기 책임
    {cli,ifc-converter}/         기존 서비스
  agents/skills/                 기존 Editor 개발 스킬만; 공용 owner 복사 금지
  resources/
    lib/core/                   scene 순수 로직, ARR 계산 코드 유입 금지
    <기존 자산 및 검증된 신규 자산>/
  infra/
    dev/                        한 번에 기동·상태·종료; Windows 숨김 실행
    config/services.json        제품 서비스 정의·공용 agent endpoint/소유권 구분
    docker/                     Neo4j 등 필요한 의존 서비스 정의
    migration/                  inventory·복사·hash·DB 이전·rollback 도구
    e2e/                        기능별 이전 동등성 및 전체 제품 시나리오
  docs/
    architecture/               책임·데이터·계약 설계
    migrations/                 전수 대응표·cutover 기록
    integrations/               실제 검증 근거
    superpowers/plans/          실행 계획
```

공용 에이전트는 `D:/Data/25_ACE/agents/{OrchestratorAgent,planm,<기존 owner>,a2a,a2a_common,docs}`에 유지한다. Editor에는 API client·endpoint 설정·계약 검증·프로젝트 연결만 둔다. 코드·메모리·가상환경·실행 DB는 복제하지 않는다.

FastAPI에서 원본 Django의 `backend.*`를 직접 import하지 않는다. 독립 계산·자료 기능부터 Editor 모듈로 이전하고 완료된 기능의 원본 adapter 호출을 제거한다. Django ORM/작업 기능은 복원 데이터와 기존 ID·상태·마이그레이션을 검증하는 별도 단위로 전환한다.

주차 엔진 등은 의존성 단위별로 계산·저장·실행을 구분해 이전한다. 아직 옮기지 않은 기능은 원본 서버 호출을 명시적으로 유지하고 미완료로 표시한다. 공통 계약 패키지는 실제 공유 소비자가 생길 때만 추출한다.

## 원본 → 목적지 및 기능 책임

| 원본 | 최종 위치·처리 | 검증할 사용자 동작 |
|---|---|---|
| ARR/backend의 활성 계산·자료·저장·API | backend/app/modules의 해당 기능과 api/adapters | 대지·법규·설계 API와 기존 계산·저장 동일성 |
| ARR/frontend/src/land | features/land-analysis | 지도 선택·주소/PNU·표고·경계·규제선 |
| ARR/frontend/src/law | features/law | 검색·스트리밍·원문·분야·오류 |
| ARR/frontend/src/design | massing/masterplan/parking/elevation 및 scene adapter | BOOK·매스 생성/수정·대안·배치·주차·입면·근거 |
| ARR 프론트 이력·계정·설정 | projects/agent-workspace/settings | 기존 데이터 열기·설정 저장·권한 |
| AG-frontend | 대응 기능별 경량 UI | 입력·첨부·중단/재개·이력·비교·내보내기·팀/MCP/갤러리 등 전수 대응 |
| AG backend 중 실제 사용 기능 | Editor 제품 modules 또는 외부 공용 agents의 해당 owner | Studio 없이 동작; 중복 실행 엔진 신설 금지 |
| 공용 agents/<이름> | `D:/Data/25_ACE/agents/<같은 이름>` 유지 | Editor 및 다른 소비자의 A2A 요청·receipt·격리·owner 기억/지침 |
| 비활성 legacy·실험·연구 | 백업·별도 보존 자료와 명시적 backlog | 사용 경로 전수 조사; 제외 결정 없이 기능 목록에서 지우지 않음 |

모든 활성 사용자 동작은 `이식`, `동등 기능으로 대체`, `미구현/막힘` 중 하나와 검증 근거를 갖는다. 중복 화면은 하나로 합치되 입력·결과·저장 기능을 빠뜨리지 않는다. 비활성 기능을 제품에 자동 활성화하지 않으며 복원 필요 여부를 별도 기록한다.

## 프로젝트·실행·데이터

- Editor `project_id`를 제품 기준으로 사용한다. 기존 `owner_project_id`, `branch_id`, `scene_id/revision`, ARR `job_id/design_id/analysis reference`는 namespace를 포함한 연결표로 관리한다. 같은 문자열을 같은 객체로 가정하지 않는다.
- 제품 DB: 프로젝트·사용자 권한·외부 ID 대응·산출물 참조. Django DB: ARR 분석/설계 기록. Orchestrator store: 실행·checkpoint·receipt. Scene store: 편집 가능한 그래프. Neo4j/vector 저장소: 기존 검색 자료. 각 데이터는 한 소유자만 쓰며, 물리 DB 병합은 이번 이전의 선행 조건이 아니다.
- 제품 런타임의 목표 위치는 Git 외부 `D:/Data/25_ACE/runtime/editor/{product,land,regulations,design,scenes,artifacts,logs}`다. 공용 agents의 실행 DB·checkpoint·메모리는 기존 owner 관리 위치에 유지한다. 제품 SQLite는 온라인 backup API 또는 쓰기 중단 후 일관된 snapshot으로 옮긴다. WAL 파일을 무시한 생파일 복사는 금지한다. Neo4j와 파일 artifact도 각각 복원 검증한다.
- 긴 작업은 Orchestrator가 조정하고 ARR의 기존 job ID를 연결한다. 한 사용자 요청에서 두 실행기가 같은 계산을 중복 시작하지 않는다. 실행 취소·추가 입력·재시도는 owner가 실제 지원하는 계약으로 검증한다.
- 산출물 → 3D 적용은 입력 revision/hash·좌표계·단위·층 기준을 검증하고, 같은 artifact를 재적용해도 중복 객체가 생기지 않아야 한다. DWG·주차·입면·인테리어 모두 scene 단일 쓰기 경계를 사용한다.
- Systems/DomainExpert/InteriorDesign의 partial/blocked는 제품 화면에도 유지한다. 폴더 이전이 전문 기능 완성을 뜻하지 않는다.

## 화면·운영

프로젝트 화면은 대지 → 법규 → 프로그램 → 매스 → 배치/주차 → 평면 → 입면/실내/설비 → 검토 흐름으로 연결한다. `/projects/:projectId/<feature>`에서 같은 context를 사용한다. 기존 `/dwg`, `/planm`, `/editor`, `/land`, `/agents`, `/runs/:id`와 scene 링크는 초기 이식 동안 보존하고, 이후에도 유효한 진입 또는 명시적 프로젝트 선택으로 연결한다.

최종 사용자 주소는 하나다. workbench가 UI 진입점, Next editor는 같은 origin의 `/editor`, FastAPI는 `/api/v1`을 담당한다. Django·scene MCP는 제품 서비스, 공용 worker·A2A는 외부 서비스다. registry는 아래 source_owner/lifecycle/management 계약을 사용한다. Editor 기동 도구는 세션 소유 프로세스만 관리하고 지속 서비스는 endpoint/health/config identity를 확인해 연결한다. Editor 종료·재시작 시 공용 프로세스를 중단하지 않는다. 공용 서비스 기동·복구는 별도 호스트 운영 도구가 담당한다.

### 재검토 보완: 소스 소유와 프로세스 수명 구분

`ownership`만으로 프로세스 종료 권한을 결정하지 않는다. registry는 `source_owner: editor | agents`, `lifecycle: session | persistent`, `management: editor-session | domain-host | agent-host`를 구분한다. Editor 종료는 자신이 생성한 `management=editor-session` 프로세스만 종료한다. 재사용한 프로세스는 종료하지 않는다.

Editor 내부 ARR 도메인 서비스도 공용 agents와 다른 제품이 사용한다면 `source_owner=editor, lifecycle=persistent, management=domain-host`다. 소스는 Editor에 있지만 UI 세션과 별도로 기동·유지한다. 공용 agent는 `source_owner=agents, lifecycle=persistent, management=agent-host`다. 브라우저/작업창을 닫았다고 계산 서비스가 꺼지지 않아야 한다.

의존 순서는 데이터/도메인 호스트 → 공용 agent 호스트 → 제품 세션이다. 에이전트의 domain 요청은 계산 전용 경계로 전달하며, 동일 요청을 다시 Orchestrator에 보내는 제품 workflow API를 호출하지 않는다. 내부 호출에 run/context ID, hop count와 기한을 전달해 순환·무한 대기를 검증한다. domain readiness는 agent readiness를 필수로 기다리지 않는다.

ARR 소스 이전 검사는 제품뿐 아니라 공용 agent의 `ARR_BACKEND`·editable install·sys.path·작업 스크립트·자산 참조도 포함한다. 발견된 각 의존에 HTTP 전환 또는 새 Editor 소유 package 경로를 명시한다. 공용 agent가 Editor 소스를 import해야 하는 기존 예외는 별도 환경과 버전 계약으로 고정하고 순환 import를 금지한다. 원본 ARR 경로가 에이전트를 통해 간접 참조돼도 이전 완료가 아니다.

소비자 격리는 이름 앞에 prefix를 붙이는 것만으로 완료되지 않는다. 서버가 인증된 consumer_id/principal을 결정하고 project/branch/run/artifact/interrupt의 소유권을 확인한다. 새 binding은 tenant scope와 함께 기존 owner ID로 대응시킨다. 기존 local 데이터는 명시적 legacy scope에 남기며 다른 제품으로 자동 공개하지 않는다.

## 전체 완료 기준

1. 전수 기능표의 모든 활성 동작에 이식 또는 동등 대체와 통과 근거가 있다. 미완성은 0건 또는 별도 합의된 잔여 범위로 명시한다.
2. 새 checkout+제품 데이터 복원으로 재현 가능하다. 예전 ARR/AG/AG-frontend 소스 경로에 제품이 의존하지 않는다. 외부 공용 agents의 서비스 연결은 유지하며, 연결 불가 시 unavailable을 표시한다.
3. 기존 DB·설계·도면·주차·3D 결과를 열고 수정·저장·재열기·실패 복구까지 검증한다.
4. 숨김 기동·종료·재부팅 복구·로그·백업·rollback이 하나의 제품 운영 기록으로 제공된다.
5. 원본 삭제는 완료 기준이 아니다. 보호된 원본·이력·snapshot을 보존한 상태로 새 제품만 운영할 수 있어야 한다.
6. 공용 agents에서 소비자/프로젝트별 권한·멱등 키·결과·취소 범위를 검증한다. Editor 종료가 다른 제품의 요청이나 작업에 영향을 주지 않는다.
