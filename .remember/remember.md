# Handoff

## State

PLAN은 스캐폴딩 단계를 지나 통합 제품 저장소가 되었다. 매스 입력에서 대안 생성,
검증, 시각 리뷰, 승인, DXF 핸드오프, 승인 후 DWG 검사까지 하나의 흐름으로 동작한다.

정본 구조 (2026-08-10 모듈화 완료):

- `frontend/` — Backend HTTP만 호출
- `backend/app/` — api, schemas, modules(20개), adapters(planm_agent, dwg_client, planm_engine)
- `backend/engine/` — 기하/그래프/제약/메트릭, Shapely 유일 경계
- `agents/planm/` — SOUL, RULES, agent.yaml, contracts 3종, skills 5개, workflow, memory
- `agents/runtimes/gitagent/` — 범용 런타임
- `agents/dwg/` — 벤더링된 독립 DWG 제품
- `infra/docker`, `infra/dev`, `infra/e2e`, `resources/*`, `docs/`

루트 legacy(`agent/`, `external/`, `deploy/`, `scripts/`, `datasets/`,
`experiments/`, `research/`, `browser_tests/`, 루트 `engine/`)는 제거됨.

제품 API 라우트 (`PLANM API v1.0.0`):
`/api/v1/planm/runs`, `.../{run_id}`, `.../alternatives`,
`.../alternatives/{id}/preview`, `.../approval`, `.../dwg/handoff`,
`.../dwg/inspection`, `.../artifacts/{path}`.

## Next

1. `agents/dwg` npm high advisory 1건 미해결.
2. 레이아웃 생성기는 여전히 결정론 베이스라인. 인접성 인식 생성기로 교체 여지.
3. 밸리데이터에 문/최소 복도폭/오목 인식 파티션 미구현 (V1 계약 밖).

## Context

실무용 자동화가 목적이지 이미지 생성이 아니다. 비율 하드코딩 금지. 매 루프마다
PNG/HTML 아티팩트를 실제로 확인한다. 하드 유효성과 소프트 점수를 섞지 않는다.

목표/경계/검증 명령은 루트 `CLAUDE.md`와 `docs/architecture/repository_layout.md`에
정리되어 있다.
