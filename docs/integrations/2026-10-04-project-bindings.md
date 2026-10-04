# 재검토와 프로젝트 연결 검증

현재 범위는 로컬 단일 사용자 제품이다. 원격 배포용 인증/다중 사용자 ACL 완료를 뜻하지 않는다.

## 구현

- `/projects`와 `/projects/:projectId`를 기존 셸에 추가했다. owner project/branch와 Pascal scene/project/revision을 별도 ID로 연결한다.
- `modules/platform/repository.py`는 외부 데이터 경로의 SQLite에 메타데이터만 저장한다. schema v2 migration과 삽입은 BEGIN IMMEDIATE로 원자화한다. scene 그래프와 owner 실행 DB를 복제하지 않는다.
- owner 프로젝트 목록은 명시한 state DB를 read-only로 조회한다. 없는 파일은 생성하지 않는다.
- scene 소유자가 현재 local 사용자 또는 기존 unowned(null) 장면인 경우만 연결한다. 다른 소유자·project/revision 불일치·없는 scene은409, malformed scene contract는502, 통신 장애는503이다.
- 변경 요청의 Origin은 명시한 `EDITOR_PUBLIC_URL`과 대조한다. 브라우저 user_id 입력은 거절한다.
- 개발 launcher는 owner API 주소, scene 주소, 별도 저장 경로를 설정한다. owner 재사용 시 state 경로의 SHA256 config_id를 검사해 다른 DB 인스턴스를 거절한다. 전체 스택 재기동은 아직 검증하지 않았다.

## 재검토에서 수정한 문제

독립 리뷰가 다른 소유자 장면 허용,404 오분류, 잘못된 owner DB 재사용, migration 원자성, 누락 projectId를 null로 오인하는 문제를 지적했다. 모두 수정하고 관련 회귀 검사를 추가했다. Pascal project ID와 owner project ID의 동일성 가정을 제거했다.

실제 브라우저 테스트에서 proxy 통과 POST의 Origin 비교가403으로 실패했다. 제품 공개 주소를 명시하는 계약으로 수정 후 성공했다. 이전 세션의 환경 설정+숨김 기동 명령은 자동 검토에서 거절됐으나, 명시적 app factory/격리 경로를 사용한 감독된 실행과 단순 hidden launcher는 허용됐다. 전체 접근 권한 문제로 단정하지 않는다.

## 검증된 증거

- 제품 catalog/project 테스트18 통과, owner registry/API20 통과, 개발 설정12 통과, route2/구조 경계2 통과, frontend build 통과.
- 실제 browser→Vite5186→FastAPI18432→owner8792 목록, 프로젝트 연결·stale revision409·상세 재열기, 기존 목록 UI 회귀: Playwright4 통과(그 중 live2).
- isolated scene `platform-binding-20261004`, owner fixture `infra-probe/main`, product project `085aefa2d2b84f678dd99857abbaeb39`. API 재시작 후 같은 바인딩 유지. 기존 프로젝트 설계 상태는 수정하지 않았다.
- 증거는 `%LOCALAPPDATA%/CodexMigrationBackups/editor-platform-20261004/editor/platform-live/`와 복원 runtime의 `test-results/editor-live-{agents,project}.png`에 있다. 원본 AG/AG-frontend와 기존 scene은 보존했다.

## 다음

Task4: 이 바인딩을 기준으로 요청 멱등성, owner durable run, 진행·현재 interrupt 입력·실행 이력·결과 receipt를 연결한다. 현재 작업 요청·결과 및 전문 owner 완성은 미구현/미검증이다. 구현 상태를 unknown에서 완료로 승격하지 않는다.
