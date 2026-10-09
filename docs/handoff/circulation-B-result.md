# B. 독립 기하 검증 담당 결과 (Independent Geometry Validation Result)

- **작업 일시:** 2026-10-09
- **작업자:** Gemini (독립 기하 검증 담당)
- **작업 저장소:** `D:/Data/25_ACE/editor`
- **소유 파일 변경:**
  - `backend/app/modules/design/generation/maas/masterplan/validation_circulation.py` (신규 독립 검증 엔진)
  - `backend/app/modules/design/generation/maas/masterplan/validation.py` (최소 연결)
  - `backend/tests/masterplan_engine/test_circulation_validation_B.py` (전용 검증 테스트 신규)

---

## 1. 독립 증거 스키마 및 검증 항목

생성기(`planner.py` / `parking_modules.py`)의 자기선언(`receipt`)을 일절 신뢰하지 않고, 원시 기하 형상(GeoJSON Features)으로부터 독립적으로 재측정하는 증거 스키마를 수립했습니다:

```json
{
  "id": "check_id",
  "check_id": "check_id",
  "status": "passed | failed | unknown | not_applicable",
  "measured": "<실측 수치 또는 형상>",
  "required": "<요구 기준 / 법규 조항>",
  "source": "<출처 명시>",
  "feature_ids": ["관련 피처 레이어/역할"],
  "coordinate_frame": "metric_local_m",
  "geometry_hash": "<형상 sha256 해시>",
  "note": "<검증 상세 설명>"
}
```

### 독립 검증 4대 핵심 항목
1. **`entry_corner_clearance` & `entry_approach_width`**
   - 도로 접면(frontage) 양 끝점(모서리)으로부터 진입 회랑까지의 최단 이격 거리 실측 (기준 >= 4.0m)
   - 진입 접근로의 유효 폭 실측 (주차장법 시행규칙 제6조 제1항 제5호 기준 >= 6.0m)
2. **`ramp_lower_landing_connection:{level}`**
   - 지하 각 층의 램프 착지부(`ramp_arrival`)와 주차 차로(`parking_aisle`) 간의 직접 접촉/교차 면적 실측
   - 램프 출구가 차로와 단절된 경우 즉시 `failed` 판정
3. **`dead_end_spurs_clean:{level}` (지하 잉여 가지 차로 검출)**
   - 주차 구획, 램프 착지부, 순환 루프(Ring Loop), 적법한 6m 회차 공간을 제외한 잔여 차로 면적 측정
   - 주차면도 없고 순환 통행도 불가능한 채 허공으로 뻗은 잉여 가지 차로가 15㎡(반 구획 면적) 초과 시 `failed` 판정
4. **`swept_path_design_vehicle` (차량 궤적 한계 명시)**
   - 설계 차량 제원(`length_m`, `width_m`, `wheelbase_m`, `min_turn_radius_m`)이 누락된 경우, 임의 승용차 가정을 배제하고 명시적 **`unknown`** 상태 및 필수 파라미터 요구 목록 반환

---

## 2. 테스트 결과

* `backend/tests/masterplan_engine/test_circulation_validation_B.py`: **5 passed in 0.33s**
  - `test_independent_evidence_schema`: 7개 필수 필드 스키마 준수 검증
  - `test_corner_entry_caught_and_failed_by_validator`: 모서리 급커브 진입 시 독립 검사기 실패 판정
  - `test_deception_test_false_receipt_caught`: 생성기가 `full_width_connected: True`를 허위 선언해도 실제 형상 단절 시 실패 판정
  - `test_dead_end_spur_detected`: 무목적 지하 가지 차로 감지 및 실패 판정
  - `test_swept_path_returns_unknown_without_vehicle_parameters`: 차량 제원 부재 시 `unknown` 반환 및 요구 항목 명시 검증

* 기존 검증 모듈 호환성:
  - `test_basement_validation_20260921.py`: **10 passed**
  - `test_candidate_diagnostics.py`: **1 passed**

---

## 3. 한계 및 전달 사항

* **외부 승인을 의미하는 포괄적인 '기하증명 완료' 표현을 배제**하며, 각 항목별 실측치와 한계를 개별 셀 단위로 보고합니다.
* 차량 궤적 시뮬레이션은 건축주/인허가청에서 지정한 설계 대상 차량의 축거/윤거/최소회전반경이 제공되어야 확정 가능함을 명시합니다.
