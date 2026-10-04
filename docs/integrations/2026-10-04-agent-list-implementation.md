# 첫 에이전트 목록 연결 구현

후속 검증: [프로젝트 연결과 live browser 증거](2026-10-04-project-bindings.md)가 아래 과거 기동 제한/미검증 상태를 갱신한다. 실제 목록과 프로젝트 브라우저 검증은 이제 통과했으며 실행 요청은 여전히 남아 있다.

## 구현 범위

- 기존 Vite 앱 `/agents`에 lazy 화면, 검색, 구현/연결 상태, 로딩·오류·빈 결과·재시도를 추가했다. AG-frontend 목록 표현을 기능별 폴더로 선별 이식했다.
- `GET /api/v1/platform/agents`는 `EDITOR_ORCHESTRATOR_URL`의 `/editor/v1/agents`를 호출한다. 설정 누락·통신 실패는503, 잘못된 계약은502이며 빈 성공 목록으로 숨기지 않는다.
- owner는 기존 `observe_profiles`를 사용한다. 선언·live card 응답·local 역할을 구분하며, card 응답으로 구현 완료를 추정하지 않아 `implementation_status=unknown`이다. 실제 작업 receipt는 아직 이 API에 연결하지 않았다.
- Vite의 `EDITOR_BACKEND_URL`은 검증용 백엔드 주소를 분리하며 기본값8000은 유지한다. Studio8081 의존성은 추가하지 않았다.

## 검증

- 경로 단위2, 구조 경계2, Chrome 브라우저2 통과. 빌드 통과. 브라우저2개는 mock API 기반이며 실제 A2A 작업 실행 증거가 아니다.
- 제품 API 계약6, owner projection/기존 registry19 테스트 통과.
- 실제 owner8791 HTTP → Editor FastAPI TestClient 조회200,25개 항목. Systems/DomainExpert/Interior를 포함한 remote card 응답을 확인했다. 이것은 새 Editor 작업 제출→A2A 실행 검증이 아니다.
- 목록 JS2.64kB(gzip1.21kB), CSS0.88kB로 별도 로딩. 전체 초기 JS381.57kB는 이번 측정값이며 이전 대비 감소를 주장하지 않는다.
- 원본 checkout에 개발 의존성이 없어 기존 DWG 패키지 검사 실패 후, 보호된 복원 runtime의 planm에 lock 기반 npm ci를 실행해 build/경계/browser를 검증했다. 원본 의존성이나 lockfile을 변경하지 않았다.

## 실제 제한과 다음 작업

숨김 전체 백엔드 기동 명령이 자동 승인 검토에서 `blocked by policy`로 거절됐다. UI 설정이나 파일 권한 문제로 단정할 근거는 없다. 조회 전용 owner 하나의 기동은 허용되어 실제 HTTP를 확인했다. 전체 백엔드 서버를 요구하는 live browser 테스트는 명시적으로 skipped이며 통과로 계산하지 않는다.

다음은 전체 browser→제품 backend→owner 검증과 프로젝트 지속 저장(Task3), 실제 요청/입력/결과(Task4)다. `/projects`와 `/runs`는 아직 미연결 안내를 표시한다. geometry 변경과 전문 설계 완성은 이번 범위가 아니다.
