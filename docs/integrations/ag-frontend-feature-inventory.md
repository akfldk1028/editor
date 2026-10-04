# 경량 AG-frontend 실제 기능 조사

2026-10-04 · 읽기 전용 소스 조사. 기준은 **`D:/Data/25_ACE/AG-frontend`의 사용자 제작 경량 UI**이다. Studio 제공 프런트엔드나 Studio 전체 기능을 이식 대상으로 삼지 않는다. 아래 `src/`는 모두 이 AG-frontend 기준이며, Editor 경로는 별도 표기한다. 추천은 선택 후보이지 전체 기능 이식 승인이나 실행 검증 결과가 아니다.

**최종 제품은 Editor만 사용한다.** AG/AG-frontend는 필요한 기능을 가져올 참조·이전 소스이며 별도 AG 콘솔·상시 Studio 런타임·Studio WS를 최종 의존성으로 두지 않는다. 선택한 UI 기능은 Editor의 기존 경로와 프로젝트 context에 넣고 Editor Backend/Orchestrator에 연결한다. 현재 코드에서 Studio를 호출한다는 사실과 목표 구조를 구분한다.

## 실제 도달 가능한 화면

`src/main.tsx → app/App.tsx → app/router.tsx`가 실제 진입 경로다. `shared/ui/Sidebar.tsx`가 아래 일반 페이지로 연결하며 `/flow`만 Playground pop-out에서 열린다. route는 lazy import + Suspense/ErrorBoundary를 사용한다. 메뉴 설명 주석에 Studio가 언급되어도 이것은 **사용자 경량 UI의 실제 구현**이다.

| 실제 기능 | 소스 | 경로 / UI 도달성 | 현재 실제 backend 호출 | Editor 기존 중복 | 추천 |
|---|---|---|---|---|---|
| 작업 입력·실시간 대화·세션 선택·중단 | `features/playground/PlaygroundPage.tsx`, `useExecution.ts`, `executionStore.ts` | `/`, Sidebar Playground. 제출 핸들러에서 세션/실행 생성 후 WS start | `shared/api/client.ts`: sessions 목록/생성/조회/삭제, `sessions/{id}/runs`, POST `runs/`; `shared/api/ws.ts`: `/api/ws/runs/{id}` | PLANM 실행 진행/상태가 있지만 범용 agent 대화와는 별개 | **우선 후보:** 메시지·입력·진행 UI. 실행은 Editor/Orchestrator 계약으로 교체; 기존 Studio start 흐름 그대로 이식하지 않음 |
| 에이전트 목록·등록·삭제·health·component | `features/agents/AgentsPage.tsx`, `api.ts`, `useAgents.ts`, `components/AgentRegisterDialog.tsx` | `/agents`, Sidebar. 일괄 health는 `enabled:false` 수동 refetch | `/api/a2a/registry`, register, DELETE 이름, check-all, `/a2a/check?url=`, 이름/component | 중앙 Orchestrator owner registry와 중복 권위 가능 | **우선 후보:** 카드·검색·상태·기능 표시. registry와 호출 권위는 Editor Backend/Orchestrator. 임의 URL 등록 UI는 별도 선택 |
| 실행 이력·두 세션 비교 | `features/history/HistoryPage.tsx`, `components/SessionDetailPanel.tsx`, Playground `useExecution.ts` | `/history`, Sidebar; 선택/비교 슬롯 실제 존재 | sessions 목록 + `sessions/{id}/runs` | PLANM 대안/실행 이력, Editor scene 목록과 일부 중복 | **우선 후보:** 간결한 목록·비교 레이아웃. 메시지 비교를 geometry/artifact 검증으로 부풀리지 않음; project/run/source 기반으로 연결 |
| 팀 구성 편집·JSON·검증·저장 | `features/teams/TeamsPage.tsx`, `useTeams.ts`, `features/team-builder/` | `/build`, Sidebar. 실제 편집 패널, add/delete/reorder, save, JSON export. AgentFlow는 lazy | teams GET/POST/DELETE; update도 POST `/teams/`; POST `/validate/` | Editor 기존 화면에 같은 범용 구성 편집은 확인되지 않음 | **선택 후보/보류:** 필요한 agent 설정 일부부터. 팀 빌더 전체·모든 패턴을 필수 범위로 잡지 않음 |
| MCP 서버·tool 목록·실제 tool 테스트 | `features/mcp/McpPage.tsx`, `mcpStore.ts`, `shared/api/mcpWs.ts` | `/mcp`, Sidebar; 연결 버튼/테스트 workbench | WS `/api/mcp/ws/{session_id}?server_params=...`, operation list_tools/call_tool/list_resources/read_resource | Editor Pascal MCP3917과 역할 다름: 현재 화면은 범용 외부 MCP client | **보류:** 필요한 도구 조회 UI만 후보. 임의 서버/stdio 실행 workbench는 기본 이식 제외; server adapter 정책 필요 |
| 템플릿 목록·상세·팀 가져오기·동기화·test | `features/gallery/GalleryPage.tsx`, `useGallery.ts`, `components/GalleryDetail.tsx` | `/gallery`, Sidebar. 목록/상세/import/sync 연결됨. **New Gallery는 disabled/Coming soon** | GET gallery, team import POST teams, external URL fetch(sync), POST `/validate/test` | Editor 자산 catalog와 데이터 성격 다름 | **보류:** 실제 필요한 preset만 선정. 전체 gallery·외부 sync·test를 기본 추가하지 않음 |
| 대지 분석 입력·결과 | `features/land/LandPage.tsx`, `useLand.ts`, `shared/api/arrClient.ts` | `/land`, Sidebar | `/arr/land/analyze/` POST, zones/stats GET. resolve API 함수는 있으나 `src`에서 호출 확인되지 않음 | Editor DWG/PLANM·ARR 대지 작업과 중복 검토 필요 | **선택 후보:** 기존 대지 입력에 유용한 항목만 병합. 별도 Land 앱을 자동 추가하지 않음 |
| 표시 설정·환경변수 설정 | `features/settings/SettingsPage.tsx`, `useSettings.ts`, `shared/theme/`, `features/font-scale/` | `/settings`, Sidebar 하단 | GET/PUT `/api/settings/`; 테마/font 등 일부 로컬 상태 | Editor 표시 설정·인증/비밀 설정과 구분 필요 | **표시 설정 후보**, 환경변수/키 관리 전체는 보류. 기존 브라우저 저장 방식을 비밀 저장 정책으로 채택하지 않음 |
| 배포 안내·명령문 생성·상태 확인 | `features/deploy/DeployPage.tsx`, `deployStore.ts` | `/deploy`, Sidebar. Dockerfile/명령 복사와 입력 폼 | 실제 API는 health/version 조회. 표시된 endpoint 목록은 호출 구현 증거가 아님 | Editor infra/runtime 관리와 중복 | **기본 제외:** 별도 Studio 배포 안내/설정. 필요하면 service health 표시 패턴만 재사용; 실제 배포 기능으로 기록하지 않음 |
| 실행 흐름 별도 창 | `features/playground/FlowPage.tsx`, `flowChannel.ts` | Playground `window.open('/flow', 'ag-flow', ...)`; Sidebar 없음 | 직접 backend 없음. BroadcastChannel로 Playground 상태 전달 | 편집 canvas와 agent 흐름은 별개 | **보류:** 실제 필요 확인 후. 프로젝트별 channel/cleanup 없이 전역 `/flow`를 복제하지 않음 |

## 작은 보조 기능: 연결 상태와 완성 범위 구분

| 기능 / 소스 | 확인된 연결 | 판단 |
|---|---|---|
| `features/tool-approval/` | Playground input_request를 parse하여 승인 카드/응답 표시. sessionStorage always-allow 캐시 사용 | UI 후보. 문자열 규칙/자동 승인 캐시를 Editor 권한 판정으로 재사용하지 않음 |
| `features/streaming/`, `features/export/` | Playground에 ThinkingIndicator/스크롤 처리/ExportButton 실제 import·표시 | 경량 UI 우선 후보. export가 설계 artifact 승인 또는 서버 보고서 완료를 뜻하지 않음 |
| `features/context-usage/` | Playground ContextUsageRing. turns의 tokensIn/out 합계와 DEFAULT_CONTEXT_LIMIT 계산 | 표시 후보. 실제 모델의 잔여 context 측정이라고 주장하지 않음 |
| `features/assistants/` | Playground PresetPanel 실제 연결 | preset 선택 UI 후보. 상수 preset마다 backend agent 구현이 있다는 뜻은 아님 |
| `features/model-registry/` | team-builder/ModelSelector.tsx에서 사용 | 설정 UI 선택 시만 동반 검토. 모델 카탈로그 항목은 실사용 가능/과금 검증 증거 아님 |
| `features/schedule/` | Playground에 ScheduleIndicator/Panel과 로컬 job store 연결. `schedule.hooks.ts`에 useScheduleRunner 구현은 있지만 src TSX 호출 없음 | **부분 연결:** 예약 설정 UI는 있으나 실행 scheduler 연결 완료 아님. 기본 이식 보류; 자동 실행 기능으로 제시하지 않음 |
| `features/dashboard/` | 현재 디렉터리에 components 하위 구조만 확인; router/import 검색에서 Dashboard 화면 연결 없음 | **미연결 scaffold:** 새 Dashboard 기능의 근거로 사용하지 않음 |
| `features/auth/useAuth.ts`, `shared/ui/MainLayout.tsx` | 레이아웃에서 auth 초기화; `/auth/type`, `/auth/me`, `/auth/login-url` 사용 | Editor 서버 인증에 통합할 경계. localStorage `platform-user` 또는 guest fallback을 권한 근거로 사용하지 않음 |

이번 `src` 조사에서 공통 feature-flag registry나 env 기반 기능 gate는 발견되지 않았다. React Query `enabled`는 조회 조건이며 제품 feature flag가 아니다. 테스트의 `MOCK_ENTRY`를 제품 mock 데이터로 오인하지 않는다. 반대로 disabled New Gallery나 호출되지 않는 schedule runner는 실제 제한으로 남긴다.

## 경량성 유지와 Editor 연결 원칙

- 재사용 기준은 `shared/ui/{Card,Badge,Button,Input,Toggle}`, 짧은 기능별 page/hook, lazy flow, `styles.css`의 색/간격 토큰이다. 기존 Sidebar/Header 전체 또는 새로운 거대한 통합 shell을 가져오는 결론은 내리지 않는다. Editor의 `frontend/app/planm/src/app/App.tsx`와 기존 `/dwg`, `/planm`, `/editor` 및 Next scene 링크를 보존한다.
- `app/providers.tsx`의 QueryClient 패턴은 유용하지만 현재 `['sessions']`, `['teams']` 전역 key와 단일 executionStore를 project/branch/run 범위로 바꿔야 한다. theme 로컬 설정과 실행/승인 권한 상태를 구분한다.
- 현재 AG Vite의 `/api → 8081`, `/arr → 8000`을 Editor에 그대로 붙이면 기존 DWG `/api`, PLANM `/api/v1`과 충돌한다. **목표는 Editor Backend/Orchestrator 계약**이며 영구 Studio proxy/WS 추가가 아니다. 실제 선택된 기능의 현재 호출을 backend 담당자에게 전달하여 필요한 adapter만 설계한다.
- 초기 추천은 agent 목록/상태, 작업·입력·진행 UI, 이력·비교 패턴이다. 선택된 artifact의 ID/hash/source revision과 owner partial/blocked를 읽기 전용으로 보여주는 것부터 검증한다. 이 추천이 팀 빌더·갤러리·배포·예약 전체 이식을 포함하지 않는다. 전체 에이전트 연결은 중앙 owner capability/receipt로 입증하고 모든 AG 메뉴 이식과 동일시하지 않는다.

## 확인된 오류와 다음 검증

복원 Studio baseline에서 `GET /api/runs/1`은 raw SQL 날짜 문자열에 `.isoformat()`을 호출하여500이었다. 이는 legacy endpoint의 확인된 오류지만, **현재 경량 History는 `sessions/{id}/runs`를 사용하므로 History 전체가 이 오류로 막혔다고 단정하지 않는다.** 해당 이력 endpoint는 별도 실검증 대상이다. 일반 WS 종료 시 `PlaygroundPage.tsx`가 completeExecution을 호출하는 현재 패턴도 Editor에서는 연결 종료와 owner 작업 완료를 분리해야 한다.

다음 구현 전 선택 목록을 확정하고 각 후보에 대해 route 도달 → 실제 API/이벤트 → project 격리 → 오류/partial 표시 → 뒤로가기/새로고침/cleanup을 확인한다. `package.json`의 현재 검증 명령은 `npm run build`(tsc -b + Vite), `npm run test:unit`(Vitest), `npm run test:e2e`(Playwright)다. 이번 조사는 소스·연결 추적이며 이 테스트나 유료 agent 실행을 수행한 보고가 아니다.
