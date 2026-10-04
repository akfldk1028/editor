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

Task1에서 실제 파일 snapshot·복원 결과와 링크 지원 범위를 확정하고 실행 baseline을 수립한다. 이 검증 없이 Task2 폴더 이동을 완료 처리하지 않는다. D:의 원본 보존+복사 여유가 작은 점은 Task2 실행 전에 재검사한다. 기존 연구 프로세스와 서비스는 광범위하게 종료하지 않는다.
