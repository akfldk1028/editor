# A. 배치 생성 담당 결과 (Circulation Generation Result)

- **작업 일시:** 2026-10-09
- **작업자:** Gemini (배치 생성 담당)
- **작업 저장소:** `D:/Data/25_ACE/editor`
- **소유 파일 변경:**
  - `backend/app/modules/design/generation/maas/masterplan/circulation_network.py` (신규)
  - `backend/app/modules/design/generation/maas/masterplan/parking_modules.py` (가지 차로 절제 연동)
  - `backend/app/modules/design/generation/maas/masterplan/placement_moves.py` (`entry_approach` 추가)
  - `backend/app/modules/design/generation/maas/masterplan/planner.py` (`accept_ramp` 코너 이격 검증 연동)
  - `backend/tests/masterplan_engine/test_circulation_repair_A.py` (전용 검증 테스트 신규)

---

## 1. 해결된 핵심 결함 및 구현 내용

1. **도로 모서리 즉시 꺾임 방지 및 직선 진입 확보 (`plan_entry_approach`)**
   - 도로 접면(frontage)의 양 끝 모서리에서 최소 이격 거리(`corner_clearance_m`, 기본 4~6m)를 강제.
   - 대지 내부로 유효 폭(6.0m) 및 최소 직선 깊이(`min_straight_length_m`, 6.0m 이상)의 직선 접근 회랑(Straight Approach Corridor)을 먼저 형성.
   - 접근 회랑의 끝단에서 비로소 램프(하향) 및 지상 주차(동일 레벨)로의 분기점(`branch_point`)을 형성.

2. **지하 무목적 잉여 막다른 가지 차로 절제 (`prune_useless_aisle_branches`)**
   - `docs/스크린샷 2026-10-09 194558.png`에서 지적된 Level -1 우상단 잉여 가지 차로 문제를 해결.
   - 주차 구획(Stalls), 램프 착지부(Landing/Anchors), 순환 루프(Ring Loop), 그리고 적법한 회차 여유(Turnaround, 6m)를 분석.
   - 어떠한 주차면도 없고 순환 루프에도 포함되지 않는 허공으로 뻗은 막다른 돌출 가지(Spur)를 정밀 절제.
   - 절제 후에도 모든 주차면 및 램프 착지부가 100% 전폭 접근(`full_width_stall_access`) 가능한 경우에만 안전하게 적용.

3. **신규 배치 조작 인터페이스 (`MOVES['entry_approach']`)**
   - AI 및 LLM이 선택할 수 있는 명시 조작 추가: `straight_6m`, `straight_10m`, `corner_clear`.
   - `planner.py`의 `accept_ramp`에 연동되어 진입 모서리 급커브 램프를 배제.

---

## 2. 테스트 결과

* `backend/tests/masterplan_engine/test_circulation_repair_A.py`: **6 passed in 0.74s**
  - `test_corner_immediate_turn_rejected`: 모서리 즉시 꺾임 진입 거부 검증 통과
  - `test_early_branching_before_straight_approach_rejected`: 직선 구간 이전 조기 분기 거부 검증 통과
  - `test_parking_stalls_blocking_ramp_landing_prevented`: 램프 착지부 주차면 침범 방지 검증 통과
  - `test_useless_dead_end_aisle_branch_pruned`: 무목적 가지 차로 절제 및 주차 접근성 보존 검증 통과
  - `test_circulation_generation_on_gosan_parcel`: 의정부 고산 대지 기하 연동 검증 통과
  - `test_placement_moves_accepts_entry_approach`: `entry_approach` 조작 계약 검증 통과

* 기존 모듈 및 램프 회귀 검사:
  - `test_parking_modules.py`: **11 passed**
  - `test_masterplan_placement_moves.py`: **27 passed**
  - `test_ramp_intent.py`, `test_ramp_fitting_20260920.py`, `test_ramp_access_integration_20260920.py`: **9 passed**

---

## 3. B(독립 기하 검증) 및 C(LLM·Jev) 전달 인터페이스

* **B 담당용 출력 데이터:**
  - `approach_polygon`: 직선 접근 차로 폴리곤
  - `entry_point`, `branch_point`, `centerline`: 접근 중심선 및 분기점 좌표
  - `pruned_spurs`: 절제된 잉여 가지 차로 수 및 면적 기록
* **C 담당용 조작 파라미터:**
  - `entry_approach`: `straight_6m`, `straight_10m`, `corner_clear`
