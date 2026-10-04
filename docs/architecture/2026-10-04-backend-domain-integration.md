# 기능별 백엔드 통합 — 기존 ARR 통째 이전안 대체

사용자 정정: 제품 백엔드를 `backend/arr`로 보관하는 방식은 채택하지 않는다. 기존 Editor 모듈 구조에 기능·계산·저장을 통합한다. 이 문서가 이전 통합 설계/계획의 ARR 목적지 결정에 우선한다.

## 책임과 경로

| 책임 | Editor 경로 | 이전 방법 |
|---|---|---|
| 제품 HTTP 입력·권한·오류 | `backend/app/api/routes_<feature>.py` | 기존 `/api/v1` 계약 확장 |
| 대지·주소·지형·지도 | `backend/app/modules/land/` | 조회/계산과 공급자 호출을 분리 |
| 법규 자료·검색·판정 | `backend/app/modules/regulations/` | 자료 출처·부분 판정·규칙 버전 보존 |
| 프로그램·매스·배치·주차·입면 | `backend/app/modules/{program_prior,massing,masterplan,parking,elevation}/` | 기존 모듈을 먼저 재사용하고 의존성 단위로 계산 이전 |
| 프로젝트·실행·산출물 연결 | `backend/app/modules/platform/` | 기존 영속 ID와 멱등 계약 확장 |
| 외부 공급자·공용 agents | `backend/app/adapters/` | 네트워크 경계만 유지; 이전 완료 호출은 제거 |
| 기능별 저장 | 해당 모듈의 `repository.py` | 원본 DB 복원본에서 테이블/키/데이터 동등성 검증 |
| scene 쓰기 | 기존 `backend/mcp`와 Pascal bridge | 단일 쓰기 책임 유지 |

표는 목표이며 빈 폴더를 미리 만들지 않는다. 전문 agents의 코드·메모리·실행 DB는 `D:/Data/25_ACE/agents`에 유지한다. 제품 데이터는 Git 밖 `runtime/editor/{product,land,regulations,design,scenes,artifacts,logs}`에 둔다. 크기가 작은 버전 관리 규칙 자료는 해당 기능 모듈의 `data/`에 포함한다.

## 이름 변경보다 기능 소유권 이전

ARR Django 트리를 다른 이름의 폴더로 복사하지 않는다. 각 기능마다 원본 입력/응답/예외/저장/산출물을 기록하고, Editor 모듈로 이전한 뒤 제품 API가 직접 호출하도록 바꾼다. 최종 완료 기준은 원본 체크아웃·기존 서버 없이 해당 기능이 동작하는 것이다.

Django ORM과 작업 실행에 얽힌 기능은 별도 하위 계획으로 모델·마이그레이션·작업 상태를 검증한다. 이전 중 원본 서버 호출은 기존 adapter에 명시적으로 남기고 기능표에서 미완료로 표시한다. Django app label과 저장된 ID를 이름 정리를 위해 먼저 바꾸지 않는다. 공용 소비자가 필요한 계산 서비스는 제품 UI와 독립된 지속 프로세스에서 같은 기능 모듈을 사용하도록 설계하며, 세션 종료에 연결하지 않는다.

기존 `unified-source-map.json`과 `arr-import-closure.json`의 소스 해시는 유효한 조사 증거다. 그 안의 과거 `backend/arr` 목적지는 폐기된 제안이다. 실제 이전 목적지는 `backend-domain-migrations.json`의 기능별 기록으로 확정한다. 미정 목적지를 추측해 604개 파일을 일괄 복사하지 않는다.

## 첫 이전 단위: 용도지역 목록

- 원본: `land/views.py:zones`, `land/services/zoning_mapper.py:get_all_zones`, `land/data/zoning_limits.json`.
- 새 소유자: `backend/app/modules/regulations/zoning_catalog.py`와 `data/zoning_limits.json`.
- 기존 `GET /api/v1/land/zones`의 응답 구조·순서·필드와 원본 자료의 바이트를 보존한다.
- ARR URL/서버 없이 목록을 반환한다. 자료 누락·손상은 503이며 빈 성공 목록으로 숨기지 않는다. 응답 변경이 다음 요청의 자료를 오염시키지 않게 한다.
- 기존 대지 분석·통계는 아직 원본 서비스 adapter를 사용한다. 목록 이전이 계산식·조례 검증 또는 전체 법규 이전을 뜻하지 않는다.
- 원본 자료와 복원본 해시 일치 → API 실패 테스트 → 이전 → 동등성/API/브라우저 검증 → 기능표·메모리·커밋 순서로 수행한다. 롤백은 이 API/모듈 커밋 복원이며 원본 데이터는 수정하지 않는다.

다음 단위는 주소/PNU 해석과 공급자 경계, 법규 자료·계산, 설계 실행/저장 순서로 정한다. MassAgent의 폴더 깊이 기반 import는 관련 계산 이전 전에 명시적 소스 계약으로 바꾸되 공유 실행 상태는 이동하지 않는다.
