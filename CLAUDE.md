# PLAN

건물 매스를 검토 가능한 평면 대안으로 바꾸는 제품 저장소.
`Mass -> Program -> Precedent -> Layout -> Validation -> Approval -> DXF/DWG`.

대상 용도는 근린생활시설과 오피스. 결과물은 예쁜 이미지가 아니라 **검증된 기하와
증거**다.

## 목표와 원칙

- 실무용 자동화. 최종 면적비를 제품 진실로 하드코딩하지 않는다.
- **하드 유효성과 소프트 품질을 분리한다.** `ValidationReport.accepted`는 점수
  임계값이 아니라 하드 게이트 통과 결과다. 인접성, 전면성, 건폐율, 효율, 컴팩트니스는
  자문 점수일 뿐 수용 판단에 쓰지 않는다.
- 매 반복마다 SVG/PNG/HTML/JSON 아티팩트를 실제로 렌더하고 눈으로 확인한다.
- 결정론을 유지한다. 랭킹은 `accepted -> 하드실패수 -> 위반점수 -> 총점 -> SHA-256
  기하 지문` 순. 동일 지문은 재평가하지 않는다.
- 종료 사유는 사실대로 기록한다. 예산 소진은 절대 수용을 의미하지 않는다.
- 제품 API는 LLM 공급자를 요구하지 않는다. LLM 실패를 결정론 출력으로 조용히
  대체하지 않는다.

배경: `docs/decisions/0001-v1-scope.md`, `docs/research_plan/v1_research_loop.md`.

## 모듈 소유권

| 경로 | 소유 |
| --- | --- |
| `frontend/` | 웹 UI. Backend HTTP만 호출 |
| `backend/app/api/` | 버전드 제품 HTTP 라우트 |
| `backend/app/schemas/` | 프론트-백엔드 DTO |
| `backend/app/modules/` | PLAN 도메인 로직, 런 상태, 아티팩트, 스테이지 실행 |
| `backend/app/adapters/` | PLANM 프로세스 / DWG 루프백 얇은 클라이언트 |
| `backend/engine/` | 기하, 그래프, 제약, 메트릭, 이미지 프리미티브. **Shapely 유일 경계** |
| `agents/planm/` | PLANM 정체성, 계약, 스킬, 워크플로, 메모리, 프로세스 브리지 |
| `agents/runtimes/gitagent/` | 범용 GitAgent 호스트. PLAN/DWG 코드 무의존 |
| `agents/dwg/` | 벤더링된 독립 DWG 제품 (자체 AGENTS.md 보유) |
| `infra/docker/`, `infra/dev/` | 컨테이너 정의, 로컬 런처, 구조 테스트 |
| `tests/browser/` | 제품 UI 및 시각 E2E |
| `resources/` | datasets, experiments, research, scripts |

정본: `docs/architecture/repository_layout.md`, `docs/architecture/module_map.md`.

## 의존 방향 (위반 금지)

```text
Frontend -> Backend API
Backend  -> PLANM 어댑터 -> GitAgent 호스트 -> PLANM 스킬 -> 프로세스 브리지
Backend  -> DWG 어댑터 -> 독립 DWG 프로세스 (승인 후에만)
```

- Frontend는 Backend/PLANM/GitAgent/DWG 소스를 import 하지 않는다.
- Backend는 `agents/planm`, `agents/dwg` 내부를 import 하지 않는다.
- PLANM과 DWG는 서로를 import 하지 않는다.
- GitAgent 런타임은 PLANM/Backend/DWG 코드를 import 하지 않는다.
- 모듈 간 데이터는 버전드 JSON 또는 공개 HTTP/MCP 계약으로만 오간다.
- PLANM 브리지는 Backend 엔진 명령을 환경변수로 주입받는다. Backend 경로를
  코드에 담지 않는다.
- 경로는 저장소 루트 상대만 사용한다. 절대 사용자 경로를 저장하지 않는다.

## 실행

```powershell
npm run dev              # 로컬 제품 (frontend 5173, backend 8000, dwg 4317)
npm run dev:docker       # docker compose, http://localhost:8080
```

## 검증

```powershell
python -m pytest -q                    # backend/tests
npm run test:agent                     # GitAgent 런타임 빌드 + PLANM 계약/스킬/워크플로
npm run test:dev                       # infra/dev 런처 및 구조 경계
npm --prefix frontend run build        # tsc --noEmit + vite build
npm --prefix frontend run test:boundaries
npm run test:frontend                  # Playwright 프론트엔드
npm run test:product                   # Playwright 라이브 제품 플로우
npm --prefix agents/dwg run verify:all # DWG: node + .NET 파서/CAD I/O + E2E
```

## 비제품 디렉터리

`clone/`, `logs/`, `test-results/`, `playwright-report/`, `node_modules/`,
`dist/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `.worktrees/`,
`.superpowers/`, `.remember/`.

프로덕션 import, 워크플로 경로, 설치 스크립트, 배포 명령은 이 중 어느 것에도
의존해서는 안 된다.

## V1 계약 한계

유한하고 단순한 양의 면적 단일 링 폴리곤만 받는다. 홀, 멀티폴리곤,
자기교차, 영면적 링, 곡선 엣지, 참조 외피 밖 오버행, 자동 3D 매스 슬라이싱은
V1 범위 밖이다. 대각 엣지가 있는 플레이트는 전층 교집합에서 축정렬 계획 영역을
고르는 개념기본설계 수준 폴백이며, 완전한 폴리곤 면적 계획이 아니다.
