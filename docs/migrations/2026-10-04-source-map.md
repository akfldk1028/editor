# Editor 이전 1단계: 원본 목록과 실행 기록

이 문서는 실제 수행한 작업과 미완료 검증을 구분한다. 전체 이전 완료 기록이 아니다.

## 사용자 지시와 설계 변경

2026-10-04: 계획대로 단계별 실행·점검. 프론트는 기존 라우터에 경로를 추가한다. 설계 변경 commit `7a2a9946`; 이전 계획 commit `59e7e646`.

기존 `/dwg`, `/planm`, `/editor`, scene 경로는 유지한다. 새 프로젝트/에이전트 경로는 기존 제품 셸에서 확장한다. 앱 전체를 Next로 교체하는 이전 제안은 폐기했다. 현재 단계에는 UI 구현이나 route 변경이 없다.

## 원본 범위와 용량

링크를 따라가지 않은 최초 파일 metadata 조사:

| 원본 | 일반 파일 수 | 일반 파일 bytes | 링크 수 | Git 소유 |
|---|---:|---:|---:|---|
| `D:/Data/25_ACE/editor` | 4,378 | 283,840,597 | 0 | 독립 저장소 |
| `D:/Data/25_ACE/AG-frontend` | 21,208 | 226,374,423 | 0 | 상위 `D:/Data/25_ACE`, 하위 경로만 이전 |
| `D:/Data/25_ACE/AG` | 429,653 | 12,828,462,346 | 293 | 독립 저장소, dirty 연구 결과 포함 |

이는 조사 시점 크기이며 후속 파일 변경은 새 manifest에서 확인한다. D: 여유 약14.0GB, C: 약49.6GB를 확인해 백업은 사용자 전용 `%LOCALAPPDATA%/CodexMigrationBackups/editor-platform-20261004/`에 저장했다. 원본을 삭제해 공간을 확보하지 않았다.

AG 링크는 junction285, Windows symlink2, LX_SYMLINK6이다. Linux 링크6개는 `ICLR2027-receipt/data/repro_env/{noworkflow_linux,agent_scaling_linux}/bin/{python,python3,python3.12}`에 있으며 일반 `os.readlink`에서 ValueError를 반환했다. 실제 도구 오류이며 UI 접근 설정 문제로 단정하지 않는다.

## Git 보존 검증

editor/AG/상위 저장소 각각 `git bundle create --all`, `git bundle verify`를 수행했다. 별도 bare 저장소로 clone한 뒤 기준 commit 존재를 확인했다. working/index binary patch와 status도 별도 저장했다. 원본 refs/index를 수정하지 않았다.

- editor 기준 `59e7e646`: 최초 bundle144,117,441bytes.
- AG 기준 `179fe496`: bundle53,230,082bytes.
- 상위 저장소 기준 `3f372a90`: bundle756,079,014bytes.
- 근거: 보호된 백업 폴더의 `history-restoration.json`, 각 저장소 `bundle.log`, `restore-history.log`.

상위 저장소 전체 working tree를 백업했다고 주장하지 않는다. 이전 대상은 AG-frontend이고, 상위 Git 이력은 별도로 보존했다. Git bundle만으로 AG의 untracked/ignored 파일이 복원되는 것은 아니다.

## 파일 보존 도구와 한계

`infra/migration/inventory.py`는 SHA256 inventory와 scoped Git 정보를 수집한다. `inventory.ps1`과 `verify-manifest.py`는 얇은 진입점이다. metadata-only는 복원 증거로 쓸 수 없다. 외부 Git pointer와 읽기 오류는 불완전 결과로 남긴다.

`snapshot.py`는 신규 ZIP_STORED/Zip64 파일에 파일 원문과 SHA256·디렉터리·링크 정보를 보존하고 존재하지 않는 새 경로로만 복원한다. 원본 변경, 경로 이탈, 덮어쓰기를 거부한다. 링크 대상은 따라가지 않는다. 링크 복원이 수행되지 않으면 `incomplete_links`다. SQLite 동시 쓰기의 일관된 DB backup이나 NTFS 전체 권한/스트림 복제와 같다고 주장하지 않는다.

## 실제 발견한 문제

- 최초 AG-frontend snapshot은 최종 트리 비교에서 변경이 감지되어 실패했다. 완료 백업으로 사용하지 않으며 원인을 설정 탓으로 추정하지 않는다.
- 최초 AG snapshot은 LX_SYMLINK 읽기 오류로 실패했다. 지원되지 않는 링크를 일반 파일로 바꾸거나 빼고 성공 처리하지 않는다.
- 루트 `.git`이 없는 AG-frontend의 상위 Git 정보가 누락되는 도구 문제는 실패 테스트로 재현해 scoped ancestor 조회로 수정했다.

후속 수정: Windows의 읽기 전용 `FSCTL_GET_REPARSE_POINT`로 링크 자체의 raw bytes와 SHA256을 보존한다. LX_SYMLINK6개에서 실제 읽기 검증을 수행했으며 target은 null로 남긴다. raw 데이터는 자동 실행·복원하지 않는다. 별도 코드 검토와 migration 테스트29개가 통과했다.

AG-frontend 재시도 `source-retry-diagnostic.zip`은21,208개 파일·226,374,423bytes를 보존했고 archive verify와 새 경로 restore가 통과했다. 최초 트리 변경 원인은 재현되지 않아 미확정이다. 별도 inventory와 복원본의 전체 비교 및 AG 대용량 검증은 후속 receipt로 판정한다.

## 실행 baseline

`node --test infra/dev/runtime.test.mjs infra/dev/compose.test.mjs`:9개 통과. 이는 서비스 설정·health identity·소유 프로세스 경계 테스트다.

실제 probe에서 editor3002, 제품 셸5173, Backend8000, Studio8081, MCP3917, DWG4317은 응답하지 않았고, Sheet8790은HTTP200이었다. 따라서 editor scene 재열기/PLANM 게시/Studio WS의 실제 baseline을 통과했다고 기록하지 않는다. 근거는 `service-baseline.json`이다.

기존 Sheet Interior 실제 브라우저 baseline은 재실행 통과: 원본/패널 보기2회 전환, 해시 불일치 거부와 원본 복귀, 탭 종료 후 canvas0, JS 오류·mutation 없음. 근거는 백업 폴더의 `interior-target-browser.json`이다. 이것이 꺼진 editor/Studio의 baseline을 대신하지 않는다.

## 실행 원칙과 다음 검증

### 후속 검증 기록

- 사용자 추가 지시: AG 기능 자체를 Editor에 통합하고 모든 에이전트를 Editor에서 발견·호출·상태/결과 확인할 수 있어야 한다. 설계 반영 commit `53b87575`. [연결표](../integrations/agent-connection-matrix.md)는 선언된 25개 중앙 profile과 별도 PLANM/도면/PPT/Studio 구성요소를 구분한다. 선언 수는 실제 연결 성공 수가 아니다.
- AG-frontend `verify-restored.json`, editor `verify-restored-v2.json`: 각각 독립 manifest 비교에서 verified=true, missing/changed/extra/errors 모두 빈 목록. editor archive는 `4a4bebe2` 시점이며 이후 설계 commit까지 포함하는 최신 백업이라고 주장하지 않는다.
- 검증 후 editor 복원본에만 의존성을 설치해 실행 baseline 작업 공간으로 사용했다. 보존 archive는 변경하지 않았다. 의존성 설치 이후 복원 작업 공간은 원본과 byte-identical한 상태가 아니다.
- Git status의 clean/process filter가 LFS 저장소 등을 변경할 수 있음을 임시 marker fixture로 재현했다. inventory는 실제 tracked 경로에 적용되는 외부 filter가 있으면 status를 생략하고 `git_state_complete=false`를 기록한다. 파일 보존과 Git 상태 조사 완료를 구분한다. 후속 migration suite: **32 passed**.
- 격리된 editor 복원 환경에서 capture-protocol/core/MCP build 3개 및 UI 관련 build 4개 통과. 별도 `editor/runtime-baseline/pascal.db`에 scene POST 201, GET 200 및 graph 일치 확인. 실제 Chrome `/scenes`, `/scene/restore-baseline-built-20261004` 각각 HTTP200, canvas1, pageerrors0. 기본 빈 부지의 재열기이며 고급 편집/PLANM/Studio 실행 통과를 의미하지 않는다.
- 임시 Windows fixture에서 junction/일반 symlink/LX_SYMLINK raw metadata 복원이 각각 성공했다. 전체 AG 링크 293개 복원 성공을 의미하지 않는다. AG archive와 실제 전체 복원 검증은 아직 진행 중이다.
- AG snapshot v2의 최종 비교 실패는 디렉터리 4개의 `st_size`만 20480/65536→0으로 달라진 사례였다. Windows 일반 디렉터리의 allocation 크기를 signature에서만 정규화하고 파일·링크 크기와 디렉터리 identity/time, 전체 경로 비교는 유지했다. 테스트에서 크기 조회 차이는 허용하고 mtime 변경은 여전히 거부한다.
- `93f11598`: 명시적 `restore --restore-reparse` 지원. 새로운 경로에 일반 파일을 먼저 복원하고 링크를 마지막에 생성해 원시 bytes와 파일 해시를 다시 검증한다. 기본 동작은 계속 기록 전용이며 Windows 외 선택형 복원은 거부한다. 전체 migration suite **42 passed**. AG snapshot v3 재시도 중이며 실제 전체 복원 성공은 아직 주장하지 않는다.
- 실제 복원본 FastAPI의 읽기 전용 baseline: OpenAPI/docs200, 없는 run404, `/health`404(미구현). 실제 PLANM config/schema 읽기 통과. 원본 editor 경로를 owner 탐색 anchor로만 사용하고 모든 runs는 별도 빈 경로로 설정했다. `runtime-baseline/backend/receipt.json`에 근거가 있다. PLANM 실행/게시에는 고정된 sibling owner 탐색, Gitagent 빌드 누락, 단계 subprocess 숨김 실행 검증이 남아 있다.

Task1에서 실제 파일 snapshot·복원 결과와 링크 지원 범위를 확정하고 실행 baseline을 수립한다. 이 검증 없이 Task2 폴더 이동을 완료 처리하지 않는다. D:의 원본 보존+복사 여유가 작은 점은 Task2 실행 전에 재검사한다. 기존 연구 프로세스와 서비스는 광범위하게 종료하지 않는다.

### 실제 실행 후속 결과

- AG snapshot v3 생성 성공: 일반 파일429,653개, 디렉터리50,219개, 12,828,462,346bytes, 링크293개. archive 크기13,160,330,382bytes. 생성 결과 `incomplete_links`/exit2는 링크의 기록만 끝났다는 뜻이다. `restored-files-v3 --restore-reparse` 전체 복원과 최종 검증은 진행 중이다.
- AG-frontend 복원본 `npm.cmd run test:unit`:12files/96tests 통과. `npm.cmd run build`:TypeScript/Vite 통과. 선택한 소스·설정194개 해시 불변. `AG-frontend/runtime-baseline/`에 로그와 receipt를 남겼다.
- Editor `5e36616f`: 명시적 절대경로 `PLANM_AGENT_DIR`, Windows stage host 숨김 실행. 관련9개 테스트를 직접 재실행했다. 복원 환경에 해당2개 파일을 overlay하고 Gitagent의 자체 lockfile로 `npm ci` 및 build를 수행했다. 따라서 뒤의 PLANM baseline은 최초 archive 그대로의 실행이 아니라 명시된 수정 후 실행이다.
- PLANM owner `6a059ee`와 `151c59d`: Node host·5개 skill wrapper·bridge 숨김 실행, 실제 Windows에서 중간 wrapper가 잃던 stdout/stderr를 명시적 pipe로 전달. 최초 failed run `ca87743cb91a4b10800cf740d6e5eb7b`와 경계별629bytes→0bytes 증거는 보존했다. Python19(실제5개 subprocess 사슬 포함), Node4 통과. Owner memory commit `4d904cd` 및 후속 `151c59d`에 맥락 기록.
- 수정 후 실제 PLANM API run `858fab437a334726904a2116bde47539`: delivered, accepted alternatives `alternative-c`,`alternative-a`. 격리 fixture에서 `alternative-c` 선택 후 실제 MCP3917 게시와 Next3002 재조회 통과. scene `868e0a5e9231`, version2, nodeCount321(5levels/50zones/124walls/40doors), 변환 경고 없음. 관할·기준일·층 법규 맥락·피난거리 분류는 unresolved로 보존한다. 법적 승인이나 전체 agent 연결 완료가 아니다.
- 근거: `runtime-baseline/planm-live-v2/{receipt,scene-summary}.json`. 실행 시작 당시 owner HEAD와 수정 중 파일 상태를 구분한다. 테스트된 wrapper 수정은 이후 `151c59d`로 커밋됐다. 전용 Backend18432는 종료했고 격리 MCP/Next는 유지했다. 게시 장면의 브라우저 시각 검증은 후속 진행 중이다.
- Studio 소스 subtree만 별도 보관·검증·복원:79,919files/916,154,297bytes/links0. 기존 venv의 autogen-ext0.5.7은 소스가 요구하는 `StreamableHttpServerParams`를 제공하지 않아 시작 실패했다. 별도 venv에 선언 의존성을 설치한 뒤에도 MCP2.3.0의 `RequestContext` 호환 문제가 드러났다. 원본 venv와 제품 소스는 변경하지 않고 격리 환경에서 재검증 중이다. 실패를 세션/WS 통과로 기록하지 않는다.
