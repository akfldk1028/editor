# AG → Editor 기능 대조 및 검증 기준

2026-10-04. 사용자 지시: Editor를 주 제품으로 사용하고, 채택한 기존 기능을 프론트와 백엔드까지 완결한다. 기능 폴더 존재나 에이전트 목록 응답만으로 흡수 완료로 판정하지 않는다.

## 원본 근거

- 프론트: `D:/Data/25_ACE/AG-frontend/src/app/router.tsx`의 10개 경로 및 `src/features/`의 22개 기능 폴더.
- HTTP 계약: `src/shared/api/client.ts`, `src/features/agents/api.ts`, `src/shared/api/arrClient.ts`.
- 실행 전송: `src/shared/api/ws.ts`, `src/shared/api/mcpWs.ts`.
- AG 백엔드: `D:/Data/25_ACE/AG/autogen_a2a_kit/autogen_source/python/packages/autogen-studio/autogenstudio/web/routes/`.
- 원본에 코드가 있다는 사실은 원본 기능의 현재 정상 동작을 입증하지 않는다. 아래는 소스 대조표이며 실서비스 검증은 별도다.
- 상세 도달성 근거는 기존 `docs/integrations/ag-frontend-feature-inventory.md`, `ag-backend-feature-inventory.md`를 따른다. 이 문서는 이식 현황 대조표다. API 함수가 있어도 화면에서 사용하지 않는 항목은 기존 동작으로 계산하지 않는다.

## 기능별 현황

2026-10-04 추가: ARR `DefaultAgentFlowPanel`의 대화·흐름도·직접 명령도 통합 대상이다.
현재 Editor 실행 상세에는 저장된 요청·응답 표시를 연결했고 실제 A2A 기록의 복사본으로 HTTP/브라우저 검증했다.
직접 에이전트 간 중계 대화, 토폴로지, 직접 명령 및 스트리밍은 남아 있다.
상세: `../integrations/2026-10-04-agent-communications.md`.

| 원본 화면/기능 | 원본 백엔드 또는 저장 | Editor 대응 | 상태 / 남은 검증 |
|---|---|---|---|
| `/` Playground: 작업 입력·세션·실행 | sessions, runs, 실행 WebSocket | 프로젝트 내 작업 입력, `/runs/:id`, platform API → owner | 구현 중. 현재 health 템플릿만. 일반 작업·첨부·메시지·중단·재개 미완성 |
| `/history`: 실행 이력·세션 삭제 | sessions, session runs | 프로젝트 실행 목록·상세 | 구현 중. 실제 결과·검색·내보내기·보존/삭제 정책 미완성 |
| `/agents`: 목록·등록·삭제·상태 확인 | a2a registry/check/component | `/agents`, 중앙 owner catalog | 목록 연결 검증. 등록·삭제·개별 점검 UI는 미이식 |
| `/build`: 팀 목록·생성·수정·삭제·구성 | teams, validate/test | owner 작업 정의와 제품 구성의 책임 설계 필요 | 1차 범위 밖으로 보류했던 기능. 전체 흡수 완료에 포함하면 안 됨 |
| `/mcp`: 연결·도구 탐색·호출 | MCP WebSocket bridge | 기존 Editor MCP는 scene 도구용 | 범용 MCP 관리 미이식. 기존 scene MCP를 동등 기능으로 간주하지 않음 |
| `/gallery`: 구성 조회·팀 가져오기·동기화·검증 | gallery, teams, validate/test | 미구현 | 1차 보류. 원본 New Gallery는 disabled이며 생성 완료 기능으로 계산하지 않음 |
| `/deploy`: 서비스 정보·배포 안내 | health/version, 안내 콘텐츠 | 기존 Editor 기동 도구 | 원본 화면 미이식. Editor 기동 검증과 Studio 배포 안내를 분리해야 함 |
| `/land`: 주소/PNU·규제·법령·통계 | ARR land/analyze, zones, stats; resolve는 미호출 함수 | `/land` → Editor `/api/v1/land` → ARR18320 | 조회·표시 구현, 실제 PNU/수동 지역·통계 검증. 주소/실제 법령 검색 및 프로젝트 저장·scene 적용은 미검증/미구현. 원본 법령 형식 불일치와 누락된 owner 판정 보완 |
| `/settings`: 사용자 설정 | settings API, 로컬 설정 | Editor 기존 설정 | AG 설정 항목별 대응 미완성 |
| `/flow`: 별도 실행 흐름 창 | Playground 실행 상태 공유 | 실행 상세 | 미이식. 실행 상세만으로 흐름 시각화 완료 아님 |
| auth | auth/type, login-url, me | 현재 로컬 단일 사용자 | 다중 사용자 인증·권한 미이식 |
| streaming, tool-approval | 실행 WS, input_response | owner pending input 경계 | 미완성. 상태 polling은 메시지 스트리밍·승인 재개와 동등하지 않음 |
| export, context-usage | Playground 표시·메시지 export·토큰 합산 | 미구현 | 실제 모델 context 측정이나 서버 산출물로 확대하지 않음 |
| dashboard | router/import 연결 없는 scaffold | 이식 대상 기능으로 계산하지 않음 | 화면 미연결 |
| assistants, model-registry | Playground preset, 팀 구성 모델 선택 | 미구현 | preset/카탈로그와 실제 실행 가능성 구분 |
| schedule | 로컬 설정 UI, runner의 TSX 호출 없음 | 보류 | 원본 자동 실행 완료 기능으로 계산하지 않음 |
| font-scale, shortcuts, theme, i18n | 브라우저 UI 설정 | Editor 기존 UI와 대조 필요 | 충돌 없이 사용자 동작을 보존하는 방식 미확정 |

## 순서와 완료 조건

1. 실행·이력: 요청 → 영속 ID → 실행 → 진행/결과 → 새로고침 복원. 응답 유실 재시도는 같은 실행을 반환해야 한다. health 검증을 일반 실행 완료로 확대하지 않는다.
2. ARR 대지 분석: 주소/PNU 입력 → 실제 ARR 응답 → 오류·규제 근거 표시 → 프로젝트 연결. PLANM/DWG 입력과 중복 저장하지 않는다.
3. 결과·추가 입력: 현재 실행과 산출물의 소유 관계 확인, 내용 표시, 승인/추가 입력 후 이어 실행. scene 적용은 별도 검증한다.
4. 나머지 화면: 위 표의 항목별로 실제 사용 동작과 의존 API를 확인하여 이식/기존 기능 대체/보류를 기록한다. 보류를 삭제 또는 완료로 바꾸지 않는다.
5. 최종: AG/AG-frontend 서버 없이 Editor에서 채택 기능을 실행하고, 기존 DWG·PLANM·2D/3D·저장/재열기 회귀를 검증한다.

폴더는 `frontend/app/planm/src/features/` 아래 기능별 UI/API, `backend/app/api/` 아래 라우터, `backend/app/modules/` 아래 제품 기능, `backend/app/adapters/` 아래 외부 연결로 구분한다. AG 전체 복사·Studio 상시 프록시·두 번째 작업 큐를 통합 완료로 인정하지 않는다.
