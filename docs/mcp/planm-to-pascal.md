# PLANM → Pascal

PLANM이 만든 평면 대안을 Pascal 에디터의 3D 씬으로 발행한다.

```
PLANM run → 승인 → POST /api/v1/planm/runs/{run_id}/pascal
                        ↓ 층별 geometry.json 읽기
                   변환기 (backend/app/modules/pascal_bridge)
                        ↓ apply_floor_plan 플랜
                   MCP HTTP 어댑터 (backend/app/adapters/pascal_mcp.py)
                        ↓
                   Pascal MCP 서버 → 씬 → 에디터 URL
```

PLAN은 Pascal 코드를 import하지 않는다. 공개된 MCP 도구 계약을 HTTP로 호출할 뿐이라 두 제품은 서로 독립이다.

## 준비

```bash
# 1. Pascal MCP 서버 (HTTP 트랜스포트)
bun run backend/mcp/src/bin/pascal-mcp.ts --http --port 3917

# 2. 에디터
bun dev

# 3. PLANM 백엔드에 알려주기
set PASCAL_MCP_URL=http://127.0.0.1:3917/mcp
set PASCAL_EDITOR_URL=http://localhost:3002
```

| 환경변수 | 기본값 | 용도 |
|---|---|---|
| `PASCAL_MCP_URL` | (없음) | MCP 엔드포인트. 없으면 발행 요청이 503 |
| `PASCAL_EDITOR_URL` | `http://localhost:3002` | 응답의 `editor_url` 조립용 |
| `PASCAL_MCP_AUTH_TOKEN` | (없음) | `--auth-token`으로 띄운 경우 |
| `PASCAL_MCP_TIMEOUT` | `60` | 초 |

## 호출

```http
POST /api/v1/planm/runs/{run_id}/pascal
```

```jsonc
{
  "alternative_id": "alternative-c",  // 생략하면 승인된 대안
  "scene_name": "PLANM e2e",
  "furnish": true,                    // 방 타입이 매핑되면 가구 배치
  "level_height": 3.0,                // 새 레벨을 만들 때만 적용
  "dry_run": false,                   // 씬 무변경 검증
  "plan_only": false                  // Pascal에 접속하지 않고 변환 결과만
}
```

응답:

```jsonc
{
  "contract_version": "planm-pascal-publish/v1",
  "run_id": "...", "alternative_id": "alternative-c",
  "published": true,
  "scene_id": "3e5fcd377bc1",
  "editor_url": "http://localhost:3002/scene/3e5fcd377bc1",
  "plan": { "levels": [ ... ] },      // 실제로 적용된 플랜
  "totals": { "levels": 5, "rooms": 50, "walls": 200, "doors": 40, "items": 14, "areaSqMeters": 1463.22 },
  "conversion_warnings": [],          // PLANM → Pascal 변환 중 문제
  "unplaced_openings": [],            // 어느 벽에도 안 붙은 개구부 id
  "pascal_warnings": []               // Pascal 쪽 경고 (가구 배치 실패 등)
}
```

## 지오메트리 계약

변환의 입력은 `planm-floor-geometry/v1` 아티팩트다. 리뷰 JSON은 면적·폭 같은 **측정값**만 담고 좌표는 담지 않아서, 예전에는 소비자가 SVG를 역파싱해야 했다(`cad_handoff/svg_to_dxf.py`가 지금도 그렇게 한다). 이 아티팩트는 렌더 대상이 된 `LayoutCandidate`를 그대로 기록한다.

각 층의 SVG·PNG 옆에 함께 쓰인다:

```
artifacts/alternatives/<alt>/floor_001/<stem>.geometry.json
```

```jsonc
{
  "contract_version": "planm-floor-geometry/v1",
  "schema_version": 1,
  "project_id": "...", "candidate_id": "...", "floor_index": 1,
  "units": "m",
  "use_type": "neighborhood_commercial",
  "boundary": [[0,0], [30,0], [30,12], [0,12]],
  "rooms": [
    { "room_id": "sales_a", "space_type": "sales", "category": "room",
      "polygon": [[0,0], [14.4,0], [14.4,4.8], [0,4.8]] }
  ],
  "openings": [
    { "opening_id": "sales_a-door", "kind": "door",
      "connects": ["sales_a", "corridor_1"],
      "start": [6.75, 4.8], "end": [7.65, 4.8], "clear_width": 0.9 }
  ]
}
```

좌표는 반올림·정규화 없이 그대로다. 좌표가 망가진 개구부는 **건너뛴다** — 렌더러가 그렇게 하기 때문이고, 문 하나 때문에 층 전체 리뷰가 막히면 안 되기 때문이다.

## 변환 규칙

**개구부 → 벽 인덱스.** PLANM은 개구부를 두 방이 공유하는 월드 좌표 선분으로 기록하고, Pascal은 폴리곤 변 인덱스와 `t`(0..1)로 배치한다. 변환기는 개구부 중점을 방의 각 변에 투영해 가장 가까운 변을 고른다(허용 오차 0.35 m). 공유 개구부는 **정확히 한 번만** 잘린다 — 먼저 자기 외곽선에 걸린 방이 가져간다. 어느 변에도 안 걸리면 `unplaced_openings`에 남고 조용히 사라지지 않는다.

**`space_type` → Pascal 방 타입.** 가구 배치를 위한 매핑이며, 모르는 타입은 **타입 없이** 만든다. 방은 그대로 생기고 가구만 안 놓인다 — 매장을 침실로 잘못 라벨링하는 것보다 낫다. `category: "circulation"`은 타입이 매핑돼도 절대 가구를 놓지 않는다.

| PLANM | Pascal |
|---|---|
| corridor, hallway | hallway |
| lobby, entry, entrance | entry |
| toilet, restroom, bathroom, wc | bathroom |
| kitchen, pantry | kitchen |
| storage, store, warehouse | storage |
| bedroom / living, lounge / dining / laundry | 동일 |

**층 순서.** `floor_index` 오름차순. 첫 층은 씬의 기존 지상층에 그리고, 나머지는 그 위로 쌓는다.

## 주의

- **`level_height`는 새 레벨을 만들 때만 적용된다.** 첫 층은 씬의 기존 레벨을 재사용하므로 그 층의 층고는 바뀌지 않는다.
- **PLANM은 현재 창을 만들지 않는다.** 개구부가 전부 `kind: "door"`라서 발행 결과의 `windows`는 0이다. 변환기는 `kind: "window"`를 이미 처리하므로 PLANM이 창을 내보내기 시작하면 그대로 동작한다.
- 지오메트리 아티팩트가 생기기 전에 실행된 런은 발행할 수 없다. 409와 함께 재실행하라는 안내가 나온다.

## 검증된 실행

```
1. run 3f1c5ff6... -> delivered
2. accepted alternatives: ['alternative-c', 'alternative-a']
3. approved alternative-c
4. dry run -> 201  levels=5 rooms=50 walls=200 doors=40
5. publish -> 201  items=14  areaSqMeters=1463.22
   conversion warnings: 0 | unplaced openings: 0
   EDITOR: http://localhost:3002/scene/3e5fcd377bc1
```

에디터 API 교차 확인: `nodeCount 411` — wall 200 · zone 50 · slab 50 · ceiling 50 · door 40 · item 14 · level 5.
