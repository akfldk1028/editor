# PLANM "growth" 전략 — MANSION 제약성장 솔버 이식 설계 (초안, 2026-09-12)

## 목표
전 층이 수직으로 연계된 평면을 유형(오피스·병원·학교) 손규칙 없이 만든다.
편복도 손규칙(`topology_planner`)을 없애는 것이 아니라, 세 번째 전략 `growth`를
같은 루프(evaluate → regenerate)에 넣어 검증기·평가기·수직정합 규칙은 그대로 두고
**방 분할만** 유형 무관 알고리즘으로 바꾼다.

## 가져오는 것 (읽은 논문·코드 근거)
MANSION (CVPR 2026, `C:/DK/Editor/clone/MANSION`, Apache-2.0). 논문 Supp. C.2 Algorithm 2–3,
코드 `generation/llm_seed_expand.py`(1,111줄)·`seed_energy.py`(225)·`procthor_adapter.py`의
`polygon_to_grid/grid_to_polygons`.

알고리즘(확인한 그대로):
1. 자유영역 Ω_f = 플레이트 − 수직코어. 1–2 m 격자로 래스터화 (`polygon_to_grid`).
2. 컷 라운드: 토폴로지 그래프를 허브(main)에서 BFS → (부모, 자식들) 라운드 열.
3. 라운드마다 시드: MLLM이 부모 영역 그림을 보고 자식별 bbox/면적비 제안(`generate_seed_plan_bbox`),
   실패 시 몬테카를로. 시드 반경 r = r_base + k·a_r/|Ω|, 재시도마다 γ_j 배.
4. 성장(`expand_rooms`): 시드 셀에서 직사각형 성장 → L자 성장, ProcTHOR 방식. 면적 상한 = 목표×1.1.
5. 후처리: 스퍼 제거·구멍 채움 반복(≤20).
6. 후보 B=100 × 재시도 10, 토폴로지 술어(인접쌍 접촉) 만족 후보 중 에너지 최소:
   e(r) = 6·|A−a|/a + 0.2·시드거리 + 3·max(0, 내부코너−4) − 0.8·clamp(벽접촉).

한계(우리 검증기 기준): 복도 없음(main이 허브), 문 없음, 면적 ±는 에너지일 뿐 밴드 보장 없음,
최소폭·종횡비는 bbox 근사 캡, 격자 해상도(1–2 m)로 mm 정밀도 없음, 층별 독립 실행.

## 우리 파이프라인에 넣는 방식
```
program graph(순면적) ─┐
core + 원격계단(스택) ──┼─ topology_planner 1단계 재사용 (척추 복도·코어·계단 고정)
                        │
                        ▼
growth_planner (신규): Ω_f = 커버 − 코어 − 복도 − 계단
   시드 = 프로그램 그래프 zone(street/core) + 인접성(wet→core) ─ 규칙 시드 (LLM 시드는 옵션, 기존 llm_planner 재사용)
   성장 = MANSION expand_rooms (vendored, 격자 0.5 m)
   후보 = B개 → 필터: 우리 하드 게이트(면적 밴드·최소폭·종횡비·복도 접촉·경계) → 에너지 랭킹
   출력 = LayoutCandidate (격자 폴리곤 → 직교 정리 → 좌표 스냅)
                        │
                        ▼
validator / basic_design / evaluator / regeneration (변경 없음)
```
- 전략 이름 `growth`; `RuleRepairProposer`: topology 실패(infeasible) 시 `SwitchStrategy("growth")`.
- 수직 연계: 코어·계단은 `_stack_topology_stairs`와 동일 박스를 전 층에 고정(이미 있음).
- 복도: 1단계 척추를 고정 영역으로 두므로 `room_no_corridor_access`는 시드를 복도 접촉 셀로
  제한해서 만족(성장은 복도에서 멀어질 수 있으므로 필터로 보장).
- 격자 폴리곤의 L자·계단형: 최소폭 게이트로 걸러지고, 남는 것은 `_open_rectilinear`로 정리.

## 벤더링
`backend/app/modules/growth_planner/vendor/mansion/{llm_seed_expand.py, seed_energy.py, grid.py}`
+ `LICENSE`(Apache-2.0) + NOTICE. 외부 리포는 수정하지 않는다(핸드오프 §18-6).
LLM 호출·matplotlib·PipelineState 의존은 잘라내고 순수 함수만 가져온다.

## 게이트 (지표로 판정)
`python -m backend.tools.regenerate_plans --label growth-vN --rounds 3`:
- growth 라운드가 3층 전부 accepted, hard 0, relaxations 0, area_shortfall ≤ topology 라운드.
- 두 번째 유형(병원 또는 학교 프로그램 프로파일 1개 추가)에서 손규칙 추가 없이 accepted.

## 하지 않는 것
- CE2EPlan/GSDiff 가중치 이식(실험으로 부적합 확정), 새 모델 학습(오피스 데이터 없음).
- 유형별 배치 규칙 추가. 배치 지식은 프로그램 그래프(인접성·zone)에만 둔다.

## 구현 중 확정된 규칙 (2026-09-13, 혼합용도 T5)

모두 검증기·basic_design이 이미 요구하는 것을 생성 단계로 옮긴 것이며 게이트 완화는 없다.

1. **잔여실은 space_type으로 찾는다** (`open_work`, `sales`). 상가 층의 `sales_a`/`sales_b`처럼 여러 개면, 침식 후 조각을 큰 것끼리 짝짓고 모자라면 가장 큰 조각을 목표 면적비로 세로 절단한다.
2. **후면 코어**: 어느 층이든 `frontage_required` 실이 있으면 건물 코어는 후면 변에 둔다. 도로변은 임대실 몫이다.
3. **코어 깊이 상한**: 플레이트 깊이에서 복도 폭과 잔여실 최소폭을 뺀 값. 넘으면 코어 게이트 안에서 재비례하고, 불가하면 infeasible.
4. **코어 플랭크**: 코어에 붙어야 하는 습식실이 둘인 층이 있으면 코어를 플레이트 끝에서 `core_flank_width`만큼 안쪽에 둔다. 폭은 전 층 밴드 교집합에서 열이 가장 깊게 남고 밴드 여유가 큰 값이다.
5. **공용 출입 통로**: 후면 코어 층은 도로에서 복도까지 복도 폭 통로(`entry`)를 구조로 가진다. basic_design의 "도로 접한 공용 동선" 요구 때문이다.
6. **원격계단 치수와 위치**: legacy 후보가 없으면 층고의 법정 계단실 치수를 쓴다. 먼 끝 인셋은 잔여실 최소폭부터 0.5 m씩 탐색한다.
7. **열은 격자 셀 단위로 패킹**: 열 깊이 후보는 격자 선이고, 실 폭은 플랭크 셀의 정수배이며, 각 실의 x 구간이 시드 영역이 된다.
8. **층 잉여·부족 분담**: 전 실이 같은 배율(밴드 안)로 조정하고, 잔여실 예상 면적이 밴드 밖이면 배율을 다시 맞춘다.
9. **시드 블록도 면적 상한 적용**: 구조선 너머 셀이 넓은 곳에서 첫 블록이 밴드를 넘지 않게 실제 셀 면적으로 거른다.

게이트 결과: 오피스 `growth-v5` accepted, hard 0, shortfall 0, relaxations 0. 혼합용도 `mixed-growth-v2` accepted, hard 0.
혼합용도의 relaxations 23과 open_work 부족 35%는 legacy `_fit_rear_primary_program`이 전략 이전에 넣은 것이다.
이 의존을 없애려면 30×12 오피스 층에 편복도가 아닌 구조 옵션이 필요하며, 이는 별도 결정 사항이다.
