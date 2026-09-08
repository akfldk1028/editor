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

**개구부 → 벽 인덱스.** PLANM은 개구부를 두 방이 공유하는 월드 좌표 선분으로 기록하고, Pascal은 폴리곤 변 인덱스와 `t`(0..1)로 배치한다.

개구부는 **그 자리를 덮는 모든 벽에** 뚫린다. 한쪽만 뚫으면 안 된다 — 복도의 긴 벽이 각 방의 짧은 벽과 나란히 지나가므로, 방 쪽만 뚫으면 복도 벽이 문 앞을 그대로 막아선다. 평면도로는 멀쩡해 보이지만 3D에서는 지나갈 수 있는 문이 하나도 없게 된다. 변환기는 개구부 선분과 **동일선상에서 겹치는**(허용 오차 0.05 m) 모든 벽을 찾아 각 벽 기준으로 `t`를 다시 계산한다. 한 벽은 여러 개구부를 받을 수 있지만 같은 개구부를 두 번 받지는 않는다.

어느 벽에도 안 걸리면 `unplaced_openings`에 남고 조용히 사라지지 않는다.

**공유 경계는 한 번만 세운다.** 두 방이 맞닿으면 각자 그 변을 서술하므로, 그대로 만들면 그 자리에 벽이 둘 생겨 3D에서 두께가 겹친다. 변환기는 다른 벽에 완전히 덮이는 벽을 찾아 `omitWalls`로 넘긴다 — 남는 쪽은 **덮는 쪽**(복도의 긴 벽이 방의 짧은 벽을 이긴다)이고, 길이가 같으면 방 순서로 결정해 양쪽이 동시에 사라지지 않게 한다.

실측: 5층 도면에서 폴리곤 변 200개 → **실제 벽 124개**(76개 병합), 문 40개 전부 통과.

개구부는 살아남은 벽에 뚫린다. 없어진 벽을 지목한 개구부는 경고와 함께 건너뛴다.

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

## 곡선·사선

에디터 쪽은 직교에 묶여 있지 않다. 다음이 전부 실제 3D 노드로 만들어지는 것을 확인했다:

| 형태 | 결과 |
|---|---|
| 45도 회전 정사각형 | 벽 4개 전부 사선, 사선 벽에 문 정상 |
| 24세그먼트 원호 | 벽 26개, 원호 세그먼트 위에 문 정상 |
| L자 (비볼록) | 벽 6개, 슬래브 6점 폴리곤 |
| 사다리꼴 / 삼각형 | 사선 변 유지, 면적 정확 |

`resources/data/plans/shape-stress.json`이 그 플랜이다. 43벽 중 33개가 축정렬이 아니며 `verify_scene: ok`.

곡선은 폴리라인 근사다 — 세그먼트마다 벽이 하나씩 생기므로, 원호 세그먼트가 문 폭보다 짧으면 그 문은 들어가지 않는다.

**제약은 PLANM 쪽에 있다.** 레이아웃 생성기는 `orthogonal.py`이며 축정렬 사각형을 채워 넣는다. 사선 대지 경계는 받지만(12변 중 7변이 사선인 대지로 3층 30방 발행 성공), 그 안의 방은 대체로 축정렬로 나온다 — 그 실행에서는 방 204변 중 사선이 0이었다. PLANM 자신의 커밋된 샘플(`sample-irregular-12v-setback-office`)에는 방 64변 중 7변이 사선이라 불가능하진 않지만 기본은 아니다.

즉 사선·곡선 도면을 주면 에디터는 그대로 3D로 만든다. PLANM이 그런 도면을 잘 안 만들 뿐이다.

## 주의

- **`level_height`는 새 레벨을 만들 때만 적용된다.** 첫 층은 씬의 기존 레벨을 재사용하므로 그 층의 층고는 바뀌지 않는다.
- **PLANM은 현재 창을 만들지 않는다.** 개구부가 전부 `kind: "door"`라서 발행 결과의 `windows`는 0이다. 변환기는 `kind: "window"`를 이미 처리하므로 PLANM이 창을 내보내기 시작하면 그대로 동작한다.
- 지오메트리 아티팩트가 생기기 전에 실행된 런은 발행할 수 없다. 409와 함께 재실행하라는 안내가 나온다.
- 공유 경계는 **한 번만** 세워진다 (아래 참조).
- MCP 세션은 인메모리 씬 하나를 들고 있어서, 발행할 때마다 이전 결과 위에 쌓인다. 그래서 발행은 `empty-studio` 템플릿으로 씬을 초기화하고 템플릿이 딸고 오는 예시 방까지 지운 뒤 시작한다.

## 검증된 실행

```
1. run 3f1c5ff6... -> delivered
2. accepted alternatives: ['alternative-c', 'alternative-a']
3. approved alternative-c
4. dry run -> 201  levels=5 rooms=50 walls=200 doors=40
5. publish -> 201  items=14  areaSqMeters=1463.22
   conversion warnings: 0 | unplaced openings: 0
   EDITOR: http://localhost:3002/scene/098a80e351af
```

에디터 API 교차 확인: wall 200 · door 80 · zone 50 · slab 50 · ceiling 50 · item 14 · level 5 — 발행이 보고한 값과 정확히 일치하며 템플릿 잔여물은 없다.
