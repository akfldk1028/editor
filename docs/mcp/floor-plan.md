# `apply_floor_plan` — 플랜 → 3D

플래닝 에이전트가 도면을 하나의 JSON으로 넘기면 레벨·방·벽·문·창·가구를 **한 번의 호출로** 생성한다. 에이전트가 `create_room` → `add_door` → `add_window`를 수십 번 오케스트레이션할 필요가 없다.

에디터를 켜둔 채 호출하면 live-sync를 통해 브라우저에 즉시 반영된다.

## 계약

플래닝 에이전트는 이 형태를 뱉으면 된다. 길이는 미터이며, 문자열 단위(`"6 in"`, `"2.5m"`)도 허용된다.

```jsonc
{
  "plan": {
    "name": "3-bed bungalow",          // 선택
    "levels": [
      {
        "levelId": "level_...",        // 기존 레벨에 그릴 때. 생략하면 새 레벨을 위에 추가
        "label": "Ground floor",       // 새 레벨일 때의 이름
        "height": 2.7,                 // 층고 (floor-to-floor)
        "rooms": [
          {
            "name": "Living",
            "type": "living",          // 가구 배치용. 생략 가능
            "polygon": [[0,0], [5,0], [5,4], [0,4]],
            "wallHeight": 2.4,         // 선택
            "wallThickness": 0.12,     // 선택
            "color": "#60a5fa",        // 선택 (zone 색)
            "furnish": true,           // type 이 있어야 동작
            "openings": [
              { "kind": "door",   "wall": 0, "t": 0.5, "width": 0.9 },
              { "kind": "window", "wall": 2, "t": 0.5, "width": 1.2, "sillHeight": 0.9 }
            ]
          }
        ]
      }
    ]
  },
  "dryRun": false
}
```

### 좌표계

- `polygon`은 XZ 평면 위의 점 목록, **순서대로**. 최소 3점.
- **첫 점을 끝에 반복하지 않는다** — 외곽선은 자동으로 닫힌다.
- 벽은 폴리곤 변 순서로 생성된다: 변 `i`는 `polygon[i]` → `polygon[i+1]`, 마지막 변은 `polygon[n-1]` → `polygon[0]`.

### 개구부가 벽을 지목하는 방식

`opening.wall`은 위의 **변 인덱스**다. 4각형 방이라면 `0..3`. 응답의 `wallIds`도 같은 순서라서, 나중에 특정 벽을 다시 다룰 때 인덱스로 대응시킬 수 있다.

`t`는 벽을 따라가는 위치 — `0` = 시작점, `0.5` = 중앙(기본값), `1` = 끝점.

### 기본값

| | 기본 |
|---|---|
| 문 | 폭 0.9m, 높이 2.1m |
| 창 | 폭 1.2m, 높이 1.2m, 창턱 0.9m |
| 층고 | 2.5m |
| 벽 높이·두께 | core 라이브러리 기본값 (지정 시 덮어씀) |

### 가구 배치 (`furnish`)

`type`이 있어야 동작한다. 사용 가능한 타입:
`bedroom` `kitchen` `bathroom` `living` `dining` `hallway` `entry` `laundry` `storage`

배치는 방 지오메트리를 **커밋한 뒤** 계산하므로, 방금 만든 문의 통행 영역과 앞서 배치한 다른 방의 가구를 피해서 놓인다. 문이 있는 벽을 등지도록 배치되며, 문이 여러 개면 첫 번째 것을 기준으로 삼는다.

## 응답

```jsonc
{
  "dryRun": false,
  "levelIds": ["level_..."],
  "rooms": [{
    "name": "Living",
    "levelId": "level_...",
    "zoneId": "zone_...", "slabId": "slab_...", "ceilingId": "ceiling_...",
    "wallIds": ["wall_...", ...],     // 폴리곤 변 순서
    "doorIds": [...], "windowIds": [...], "itemIds": [...],
    "areaSqMeters": 20
  }],
  "totals": { "levels": 1, "rooms": 1, "walls": 4, "doors": 1, "windows": 1, "items": 5, "areaSqMeters": 20 },
  "warnings": []
}
```

## `dryRun`

`dryRun: true`면 씬을 건드리지 않고 결과 형태만 돌려준다. 지오메트리 계산과 **개구부가 벽에 들어가는지 검사까지 실제로 수행**하므로, 에이전트가 초안을 커밋 전에 검증하는 용도로 쓸 수 있다. 이때 `zoneId`·`slabId`·`ceilingId`는 `null`이고 가구는 계산하지 않는다.

## 오류 vs 경고

**오류(호출 실패)** — 계획 자체가 성립하지 않는 경우:
- `levelId`가 존재하지 않거나 level이 아님
- 새 레벨을 추가해야 하는데 씬에 building이 없음
- 스키마 위반 (폴리곤 3점 미만 등)

**경고(진행하되 해당 항목만 건너뜀)** — `warnings` 배열:
- 개구부가 없는 벽 인덱스를 지목함
- 개구부가 벽보다 넓어서 안 들어감
- `furnish: true`인데 `type`이 없음
- 가구가 통행 영역을 막거나 다른 물건과 겹쳐서 배치 실패

방 자체는 개구부가 하나 실패해도 정상적으로 만들어진다.

## 연결

```bash
# stdio — 로컬 에이전트
bun run backend/mcp/src/bin/pascal-mcp.ts --stdio

# HTTP — 원격/웹 에이전트
bun run backend/mcp/src/bin/pascal-mcp.ts --http --port 3917 --auth-token <token>
```

브라우저에 실시간 반영하려면 먼저 `save_scene` 또는 `load_scene`으로 씬을 바인딩해야 한다. 바인딩이 없으면 변경은 인메모리 세션에만 적용되고, 응답의 `persistence.status`가 `unbound`로 돌아온다.

## 검증

만든 뒤에는 기존 도구로 확인한다:
- `verify_scene` — 문 통행 영역, 아이템 겹침, 개구부 연결, 계단 관련 문제
- `validate_scene` — 스키마 수준 검증
- `check_collisions` — 충돌
- `get_level_summary` / `get_zones` — 결과 요약
