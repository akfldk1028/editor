# Codex 인계 — 마스터플랜 주차 줄 탐색 성능 최적화 (결과 불변)

작성 2026-10-09, MasterPlan 세션(Claude). 저장소: `D:/Data/25_ACE/editor`, 브랜치 그대로. 커밋은 하되 **push 금지**.

## 1. 목표 (한 줄)
`backend/app/modules/design/generation/maas/masterplan/rows.py` `row_candidates`(와 그것이 부르는 `rows_tiling.py`)를 **결과를 한 면도 바꾸지 않고** 빠르게 만든다. 목표: 아래 벤치 23~27 s → **5 s 이하**. 결과 동일성이 속도보다 우선이다. 속도를 위해 탐색 순서·동점 처리·반올림을 바꾸면 안 된다.

## 2. 왜 지금
- 이 함수가 플래너 전체 시간의 대부분이다(고산 1필지 50~290 s). 시간 예산 테스트 2개(`test_bounded_packing_20260920.py::test_large_envelope…` <12 s, `test_rows_runtime_20260920.py` <15 s)가 이 머신에서 각각 40 s·15 s로 실패한다.
- 프로파일(cProfile, 아래 벤치 1회, 총 47 s):
  - `_tile_bands_at` → `_fill_row` 2,000회가 **40 s**.
  - 그 안에서 `shapely.geometry.box()` **220,599회 = 29.6 s**. 주차면 하나마다 Polygon을 새로 만든다.
  - Polygon 생성마다 shapely 데코레이터가 `inspect.signature`를 부른다: **643,726회 = 21.9 s**. 즉 시간의 절반이 기하가 아니라 파이썬 함수 서명 검사다.
  - `intersection` 88,705회 6.6 s, `covers` 209,783회 2.1 s.
- 결론: 알고리즘은 그대로 두고 **생성·검사를 벡터화**하면 된다.

## 3. 제안 방향 (강제 아님 — 결과 동일하면 다른 방법도 됨)
1. `_fill_row`에서 주차면 사각형을 하나씩 `box()`로 만들지 말고, 한 줄의 x 좌표 배열을 만들어 `shapely.box(xmin_arr, ymin_arr, xmax_arr, ymax_arr)`(배열 입력, `shapely.creation`)로 한 번에 만든다. 또는 좌표 배열 → `shapely.polygons`.
2. `covers`/`intersection` 반복은 `shapely.prepare(g_ground)` 후 `shapely.covers(prepared, arr)` / `shapely.intersects` 벡터 호출로 바꾼다. `rows.py`가 이미 `STRtree, prepare`를 import한다.
3. 루프 안에서 변하지 않는 것(밴드 박스, `g_ground.buffer(EPS)`)은 끌어올린다 — 이미 일부 되어 있음(`g_site_b, g_ground_b`).
4. 반환하는 dict의 키·순서·값(`stalls` 각각의 `polygon`, `front`, `type`, `width_m`, `length_m`; `drive`; `entrance`; `score`; `terms`)은 **그대로**.

## 4. 결과 동일성 검증 절차 (이 순서대로, 전부 기록)
### 4.0 골든 먼저 만들기 (코드 바꾸기 전, HEAD에서)
아래 스크립트로 세 기하의 `row_candidates` 출력을 WKT로 저장한다. 바꾼 뒤 같은 스크립트로 다시 뽑아 **바이트 동일**이어야 한다.
```python
# backend/tests/masterplan_engine/fixtures/rows_golden.py  (저장 위치는 fixtures/ 아래)
import json, sys
sys.path.insert(0, 'D:/Data/25_ACE/editor')
from shapely.geometry import LineString, box
from backend.app.modules.design.generation.maas.masterplan.rows import row_candidates
RULES = {"stall_width_m": 2.5, "stall_length_m": 5.0, "accessible_width_m": 3.3, "accessible_length_m": 5.0, "aisle_width_m": 6.0}
CASES = {
  'bounded': (box(0, 0, 240, 120), box(70, 65, 170, 110), LineString([(0, 0), (240, 0)]), 120, 2, {}),
  'piloti':  (box(0, 0, 60, 60),   box(0, 2, 60, 22),     LineString([(0, 0), (60, 0)]),   20, 1,
              {'occupied_footprint': box(0, 12, 40, 22), 'allowed_angles': [0.0]}),
  'rotated': (box(0, 0, 90, 70).buffer(0), box(30, 30, 60, 60), LineString([(0, 0), (90, 0)]), 40, 2, {'allowed_angles': [37.0]}),
}
out = {}
for name, (site, fp, road, need, acc, kw) in CASES.items():
    ground = site.difference(kw.get('occupied_footprint', fp))
    rows = row_candidates(site, ground, fp, None, road, road, RULES, need, acc, limit=6, **kw)
    out[name] = [{'provided': r['provided'], 'score': round(r['score'], 9), 'angle': round(r['angle_deg'], 6),
                  'stalls': [(s['polygon'].wkt, s['type']) for s in r['stalls']],
                  'drive': r['drive'].wkt, 'entrance': r['entrance'].wkt if r.get('entrance') is not None else None} for r in rows]
json.dump(out, open(sys.argv[1], 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
```
실행: `python -X utf8 backend/tests/masterplan_engine/fixtures/rows_golden.py /tmp/rows_before.json` (HEAD) → 수정 후 `/tmp/rows_after.json` → `fc` 또는 `cmp`로 동일 확인. 다르면 **되돌린다**.

### 4.1 벤치 (같은 프로세스, 전후 번갈아)
```python
# 수정 전 rows.py를 git show HEAD:... 로 꺼내 rows_head.py로 두고 importlib로 같이 로드, bounded 케이스를 head/mine/mine/head 순으로 재서 초 단위 기록
```
기준: 이 머신에서 head 23.2 / 24.5 s. 목표 mine ≤ 5 s.

### 4.2 필지 재실행 해시 (MasterPlan 쪽 스크립트, 엔진은 editor 것을 import)
```
cd D:/Data/25_ACE/agents/MasterPlanagent
.venv-masterplan/Scripts/python.exe -X utf8 scripts/eval_siting.py --only 1168010100106770000 --out runs/siting-eval/codex-perf-20261009
.venv-masterplan/Scripts/python.exe -X utf8 scripts/eval_siting.py runs/siting-eval/inputs/gosan-practice-20261007/layout.json --out runs/siting-eval/codex-perf-20261009
```
비교 대상: `runs/siting-eval/fix1-default-20261007/<같은 파일>.layout.json`의 `handoff.metric_geometry_hash`(없으면 `geometry_hash`). **동일**해야 한다. 역삼 기준값: `91c150f4732e…`, `678251f6a60f…`(앞 12자). 고산은 `4115011300106840001-gosan-practice-20261007.layout.json`과 비교.

### 4.3 테스트
```
cd D:/Data/25_ACE/editor
python -X utf8 -m pytest backend/tests/masterplan_engine -q -p no:cacheprovider
```
208개(205 + `test_rows_piloti` 3). **머신 메모리가 부족하니(여유 2~3 GB) 파일 단위로 쪼개 돌려라.** 빨라지면 시간 예산 테스트 2개도 통과해야 한다. 통과하지 않으면 최적화가 덜 된 것이다.

## 5. 규칙
- 수술적 변경. `rows.py`·`rows_tiling.py` 밖은 건드리지 않는다. `planner.py`, `joint.py`, `agents/` 폴더 금지.
- 결과가 1 mm라도 다르면 채택하지 않는다. 부동소수 순서가 바뀌면(합산 순서 등) 결과가 달라질 수 있으니 **연산 순서를 보존**한다.
- 커밋 메시지는 이 저장소 스타일(무엇이 왜 느렸고 무엇을 바꿨고 어떻게 동일함을 증명했는지, 숫자 포함). 끝에 `Co-Authored-By: Codex <noreply@openai.com>`.
- `backend/memory/07-decisions.md` 맨 위 항목으로 한 줄 기록(날짜, 전후 초, 해시 동일, 테스트 수).
- 테스트 파일 외에 새 파일을 만들지 않는다(골든 스크립트는 fixtures/ 아래 하나만).

## 6. 결과 (Codex가 채움)
- 전/후 벤치(s):
- 골든 동일 여부:
- 필지 해시 동일 여부(역삼 2, 고산 1):
- 테스트: n passed / n failed(어느 것, 왜):
- 커밋 해시:
- 못 한 것·남은 것:
