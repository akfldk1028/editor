"""Korean statutory area criteria with exact official edition snapshots.

All applicability gates are explicit facts, not inferred from operational labels.
The snapshots establish source identity; project transitions and measurement scopes
still require their own evidence. This is a set of individual checks, not a permit.
"""

from backend.app.modules.design.generation import paths as _design_paths
from copy import deepcopy
import hashlib
import json
from pathlib import Path

SOURCE_DIR = _design_paths.package_root('law') / "data" / "facility_sources"


def source_snapshot(source_id):
    if source_id not in {"childcare_annex_1", "medical_annex_4", "disability_annex_5", "elderly_annex_4", "schools_annex_1", "youth_annex_3"}:
        raise ValueError("unknown facility source")
    data = json.loads((SOURCE_DIR / (source_id + ".json")).read_text(encoding="utf-8"))
    if hashlib.sha256(data["annex_text"].encode("utf-8")).hexdigest() != data["annex_text_sha256"]:
        raise ValueError("facility source snapshot hash mismatch")
    return data


def criterion(key, types, source_id, locator, quantity, area, basis, coefficient=0, *, fixed=0,
              conditions=None, minimum=1, quantity_range=None, terms=None, addition=0, scope=""):
    document = source_snapshot(source_id)
    effective = document["selected_effective_date"]
    rule = {"rule_id": key, "facility_types": types, "quantity_fact": quantity, "area_fact": area,
            "area_basis": basis, "coefficient_m2_per_unit": coefficient, "fixed_minimum_m2": fixed,
            "minimum_quantity": minimum, "effective_from": f"{effective[:4]}-{effective[4:6]}-{effective[6:]}",
            "required_conditions": {"current_standard_applies": True, **(conditions or {})},
            "source": {"source_id": source_id, "url": document["annex_pdf_url"],
                       "edition": document["selected_mst"], "locator": locator,
                       "annex_revision": document["annex_revision_date"],
                       "sha256": document["annex_text_sha256"], "verified_as_of": document["selection_as_of"]},
            "measurement_scope": scope, "additive_constant_m2": addition}
    if quantity_range is not None:
        rule["quantity_range"] = quantity_range
    if terms is not None:
        rule["area_terms"] = terms
    return rule


FACILITY_AREA_RULES = [
    criterion("kr.childcare.facility", ["childcare_general"], "childcare_annex_1", "별표1 3가4", "children", "facility_area",
              "childcare_facility_excluding_playground", 4.29, scope="어린이집 시설면적, 놀이터 제외"),
    criterion("kr.childcare.rooms", ["childcare_general"], "childcare_annex_1", "별표1 3가4가③", "children", "childcare_rooms",
              "qualifying_childcare_room_sum", 2.64, scope="보육실·거실·공동놀이실 합계; 각 실에 정원을 반복 적용하지 않음"),
    criterion("kr.childcare.disabled.facility", ["childcare_specialized_disabled"], "childcare_annex_1", "별표1 3나1",
              "disabled_children", "facility_area", "childcare_facility_excluding_playground", minimum=12,
              terms=[{"quantity_fact": "disabled_children", "coefficient": 7.83}, {"quantity_fact": "other_children", "coefficient": 4.29}],
              scope="장애아전문어린이집: 장애아와 비장애아 계수를 따로 합산; 놀이터 제외"),
    criterion("kr.childcare.disabled.rooms", ["childcare_specialized_disabled"], "childcare_annex_1", "별표1 3나1",
              "disabled_children", "childcare_rooms", "specialized_childcare_room_sum", minimum=12,
              terms=[{"quantity_fact": "disabled_children", "coefficient": 6.6}, {"quantity_fact": "other_children", "coefficient": 2.64}],
              scope="교실·거실·포복실·유희실·치료교실·집단활동실의 해당 합계"),
    criterion("kr.medical.single_room", ["hospital_single_room"], "medical_annex_4", "별표4 1나", "room_beds", "patient_room",
              "patient_room_excluding_walls_columns_toilets", fixed=10, quantity_range={"minimum": 1, "maximum": 1},
              scope="1인 병실별 내법 면적; 벽·기둥·화장실 제외. 2017 개정 경과조치 검토 필요"),
    criterion("kr.medical.multi_room", ["hospital_multi_room"], "medical_annex_4", "별표4 1나", "room_beds", "patient_room",
              "patient_room_excluding_walls_columns_toilets", 6.3, quantity_range={"minimum": 2, "maximum": 4},
              scope="일반 다인실, 최대4병상 조건의 개별 병실 면적"),
    criterion("kr.medical.nursing_multi_room", ["nursing_hospital_multi_room"], "medical_annex_4", "별표4 1나", "room_beds", "patient_room",
              "patient_room_excluding_walls_columns_toilets", 6.3, quantity_range={"minimum": 2, "maximum": 6},
              scope="요양병원 다인실, 최대6병상 조건의 개별 병실 면적; 노인요양시설과 다름"),
    criterion("kr.medical.icu", ["hospital_icu"], "medical_annex_4", "별표4 2라", "beds", "patient_occupancy_area",
              "icu_patient_occupancy_including_internal_station_corridor", 15,
              scope="내부 간호사 스테이션·복도 포함; 간호사실·당직실·청소실·기기창고·청결/오물실·린넨실 제외"),
    criterion("kr.medical.nicu", ["hospital_nicu"], "medical_annex_4", "별표4 2라", "beds", "patient_occupancy_area",
              "icu_patient_occupancy_including_internal_station_corridor", 5,
              scope="신생아 중환자실. 일반중환자실과 다른 계수, 같은 별도 산정 범위"),
    criterion("kr.elderly.nursing_gfa", ["elderly_nursing_facility"], "elderly_annex_4", "별표4 1가", "residents", "facility_gfa",
              "elderly_gfa_excluding_excess_parking", 23.6, minimum=10,
              scope="입소정원당 연면적. 법정 주차 의무를 초과하여 설치한 주차 면적 제외"),
    criterion("kr.elderly.group_home_gfa", ["elderly_nursing_group_home"], "elderly_annex_4", "별표4 1가", "residents", "facility_gfa",
              "elderly_gfa_excluding_excess_parking", 20.5, quantity_range={"minimum": 5, "maximum": 9},
              scope="노인요양공동생활가정 정원5~9명; 연면적 기준"),
    criterion("kr.elderly.ordinary_bedroom", ["elderly_ordinary_bedroom"], "elderly_annex_4", "별표4 4가", "room_residents", "bedroom",
              "elderly_bedroom_area", 6.6, conditions={"dementia_special_standard": False},
              scope="침실 기준. 치매전담형 별도기준을 적용하지 않는 경우"),
    criterion("kr.disability.welfare_center", ["disability_welfare_center"], "disability_annex_5", "별표5 II 시설별기준",
              "facilities", "building_gfa", "building_gfa", fixed=1000, quantity_range={"minimum": 1, "maximum": 1}),
    criterion("kr.disability.day_service", ["disability_day_service"], "disability_annex_5", "별표5 II 시설별기준",
              "facilities", "building_gfa", "building_gfa", fixed=66, quantity_range={"minimum": 1, "maximum": 1}),
    criterion("kr.disability.sports", ["disability_sports_facility"], "disability_annex_5", "별표5 II 시설별기준",
              "facilities", "building_gfa", "building_gfa", fixed=900, quantity_range={"minimum": 1, "maximum": 1}),
    criterion("kr.disability.group_home", ["disability_group_home"], "disability_annex_5", "별표5 II 공동생활가정",
              "residents", "living_room", "disability_group_home_living_room", 3.3),
    criterion("kr.kindergarten.classrooms", ["kindergarten"], "schools_annex_1", "별표1 유치원 교실 총면적 행", "authorized_students", "classrooms",
              "kindergarten_classroom_sum", 2.2, conditions={"kindergarten_classroom_transition_applies": True},
              scope="교실 합계; 교사 연면적과 별도. 해당 개정 부칙 적용 및 인가정원 확인"),
    criterion("kr.youth.sleeping", ["youth_hostel", "youth_training_lodging"], "youth_annex_3", "별표3 1나8", "lodging_capacity", "sleeping_rooms",
              "youth_sleeping_with_30_percent_family_living", 2.4, conditions={"school_age_capacity_exception": False},
              scope="가족실 거실은30%만 포함. 초·중학생 정원 가산 예외는 별도검토"),
    criterion("kr.youth.lecture", ["youth_lecture_room"], "youth_annex_3", "별표3 1나7", "rooms", "lecture_room",
              "youth_lecture_room_area", fixed=50, quantity_range={"minimum": 1, "maximum": 1}),
    criterion("kr.youth.dining", ["youth_dining"], "youth_annex_3", "별표3 1나10", "diners", "dining_area", "youth_dining_area", 1),
    criterion("kr.youth.camp", ["youth_campground"], "youth_annex_3", "별표3 1나9", "camp_capacity", "campground_area", "youth_campground_site_area", 20),
]

for facility, segments in {
    "kindergarten": [(1, 40, 5, 0), (41, None, 3, 80)],
    "elementary_school": [(1, 240, 7, 0), (241, 960, 4, 720), (961, None, 3, 1680)],
    "middle_school": [(1, 120, 14, 0), (121, 720, 5, 1080), (721, None, 4, 1800)],
    "high_school_academic": [(1, 120, 14, 0), (121, 720, 6, 960), (721, None, 5, 1680)],
    "high_school_vocational": [(1, 120, 14, 0), (121, 720, 8, 720), (721, None, 6, 2160)],
    "high_school_arts_sports": [(1, 120, 14, 0), (121, 720, 10, 480), (721, None, 8, 1920)],
}.items():
    for lower, upper, coefficient, addition in segments:
        FACILITY_AREA_RULES.append(criterion(f"kr.school.{facility}.{lower}", [facility], "schools_annex_1", "제3조 및 별표1",
            "authorized_students", "teaching_building_gfa", "school_teaching_building_gfa", coefficient,
            addition=addition, quantity_range={"minimum": lower, "maximum": upper},
            conditions={"provincial_reduction_applies": False},
            scope="교사 연면적. 전 학년 인가정원 기준, 주야간은 큰 정원. 시도 조례 감면은 별도 검토"))

for residents, area in ((1, 9.9), (2, 16.5), (3, 23.1), (4, 29.7)):
    FACILITY_AREA_RULES.append(criterion(f"kr.elderly.dementia_a.{residents}", ["elderly_dementia_a_bedroom"],
        "elderly_annex_4", "별표4 4가 침실 치매전담실 가형", "room_residents", "bedroom", "elderly_bedroom_area",
        fixed=area, quantity_range={"minimum": residents, "maximum": residents},
        scope="치매전담실 가형 1~4인실별 면적; 입소정원 전체를 각 병실에 적용하지 않음"))
FACILITY_AREA_RULES.extend([
    criterion("kr.elderly.dementia_b.single", ["elderly_dementia_b_bedroom"], "elderly_annex_4", "별표4 4가 침실 치매전담실 나형",
              "room_residents", "bedroom", "elderly_bedroom_area", fixed=9.9, quantity_range={"minimum": 1, "maximum": 1}),
    criterion("kr.elderly.dementia_b.multi", ["elderly_dementia_b_bedroom"], "elderly_annex_4", "별표4 4가 침실 치매전담실 나형",
              "room_residents", "bedroom", "elderly_bedroom_area", 6.6, quantity_range={"minimum": 2, "maximum": 4}),
])


def bind_snapshot_evidence(facts, rules, assessment_date):
    """Confirm stored rule editions only for their actually checked assessment date.

    Caller booleans cannot authenticate official source versions. Project-specific
    transition/exception facts remain supplied assertions, retained separately.
    """
    bound = deepcopy(facts)
    bound["source_edition_confirmed"] = {}
    bound["source_edition_evidence"] = {}
    for rule in rules:
        document = source_snapshot(rule["source"]["source_id"])
        confirmed = (document.get("source_edition_confirmed") is True
                     and document["selection_as_of"] == assessment_date
                     and document["selected_mst"] == rule["source"]["edition"]
                     and document["annex_text_sha256"] == rule["source"]["sha256"])
        bound["source_edition_confirmed"][rule["rule_id"]] = confirmed
        bound["source_edition_evidence"][rule["rule_id"]] = {
            "edition": document["selected_mst"], "sha256": document["annex_text_sha256"],
            "checked_as_of": document["selection_as_of"], "source_url": document["source_url"],
            "confirmation_basis": document["confirmation_basis"]}
    return bound
