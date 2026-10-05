"""
Check parking count interpretation against Graph DB rules.

PNU alone is not enough for parking count. The count depends on jurisdiction,
building/facility use, and the relevant metric such as facility area, holes,
bays, capacity, or an externally delegated housing standard. This script uses
PNU as jurisdiction context and verifies deterministic scenarios against the
ParkingRequirementRule nodes already loaded in Neo4j.
"""

import argparse
import math
import os
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv
from neo4j import GraphDatabase


@dataclass(frozen=True)
class ParkingCase:
    name: str
    pnu: str
    rule_id: str
    metric: str
    value: float
    expected_required_spaces: int | None
    expected_status: str = "computed"
    expected_accessible_min: int | None = None
    expected_accessible_max: int | None = None
    expected_accessible_status: str = "not_applicable_under_10"


CASES = [
    ParkingCase(
        name="gangnam_entertainment_99m2_seoul_ordinance_one",
        pnu="1168011800104170004",
        rule_id="parking_appendix1_row_01",
        metric="facility_area_m2",
        value=99.0,
        expected_required_spaces=1,
    ),
    ParkingCase(
        name="gangnam_entertainment_100m2_seoul_ordinance_one",
        pnu="1168011800104170004",
        rule_id="parking_appendix1_row_01",
        metric="facility_area_m2",
        value=100.0,
        expected_required_spaces=1,
    ),
    ParkingCase(
        name="gangnam_entertainment_101m2_seoul_ordinance_half_up_two",
        pnu="1168011800104170004",
        rule_id="parking_appendix1_row_01",
        metric="facility_area_m2",
        value=101.0,
        expected_required_spaces=2,
    ),
    ParkingCase(
        name="gangnam_entertainment_150m2_seoul_ordinance_two",
        pnu="1168011800104170004",
        rule_id="parking_appendix1_row_01",
        metric="facility_area_m2",
        value=150.0,
        expected_required_spaces=2,
    ),
    ParkingCase(
        name="gangnam_row2_149m2_seoul_ordinance_one",
        pnu="1168011800100910005",
        rule_id="parking_appendix1_row_02",
        metric="facility_area_m2",
        value=149.0,
        expected_required_spaces=1,
    ),
    ParkingCase(
        name="gangnam_row2_150m2_seoul_ordinance_two",
        pnu="1168011800100910005",
        rule_id="parking_appendix1_row_02",
        metric="facility_area_m2",
        value=150.0,
        expected_required_spaces=2,
    ),
    ParkingCase(
        name="gangnam_row2_225m2_half_up_two",
        pnu="1168011800100910005",
        rule_id="parking_appendix1_row_02",
        metric="facility_area_m2",
        value=225.0,
        expected_required_spaces=2,
    ),
    ParkingCase(
        name="gangnam_single_house_50m2_note4_zero_for_simple_case",
        pnu="1168011800104670003",
        rule_id="parking_appendix1_row_04",
        metric="facility_area_m2",
        value=50.0,
        expected_required_spaces=0,
    ),
    ParkingCase(
        name="gangnam_single_house_51m2_one",
        pnu="1168011800104670003",
        rule_id="parking_appendix1_row_04",
        metric="facility_area_m2",
        value=51.0,
        expected_required_spaces=1,
    ),
    ParkingCase(
        name="gangnam_single_house_199m2_round_down_one",
        pnu="1168011800104670003",
        rule_id="parking_appendix1_row_04",
        metric="facility_area_m2",
        value=199.0,
        expected_required_spaces=1,
    ),
    ParkingCase(
        name="gangnam_single_house_200m2_half_up_two",
        pnu="1168011800104670003",
        rule_id="parking_appendix1_row_04",
        metric="facility_area_m2",
        value=200.0,
        expected_required_spaces=2,
    ),
    ParkingCase(
        name="songpa_warehouse_399m2_seoul_ordinance_one",
        pnu="1171010100100010000",
        rule_id="parking_appendix1_row_08",
        metric="facility_area_m2",
        value=399.0,
        expected_required_spaces=1,
    ),
    ParkingCase(
        name="songpa_warehouse_400m2_one",
        pnu="1171010100100010000",
        rule_id="parking_appendix1_row_08",
        metric="facility_area_m2",
        value=400.0,
        expected_required_spaces=1,
    ),
    ParkingCase(
        name="songpa_warehouse_4200m2_accessible_needs_local_ratio",
        pnu="1171010100100010000",
        rule_id="parking_appendix1_row_08",
        metric="facility_area_m2",
        value=4200.0,
        expected_required_spaces=16,
        expected_accessible_min=1,
        expected_accessible_max=1,
        expected_accessible_status="needs_local_ordinance_ratio",
    ),
    ParkingCase(
        name="songpa_warehouse_10000m2_accessible_range_1_to_1",
        pnu="1171010100100010000",
        rule_id="parking_appendix1_row_08",
        metric="facility_area_m2",
        value=10000.0,
        expected_required_spaces=37,
        expected_accessible_min=1,
        expected_accessible_max=2,
        expected_accessible_status="needs_local_ordinance_ratio",
    ),
    ParkingCase(
        name="yongsan_other_15000m2_accessible_range_1_to_2",
        pnu="1117010100100010000",
        rule_id="parking_appendix1_row_11",
        metric="facility_area_m2",
        value=15000.0,
        expected_required_spaces=75,
        expected_accessible_min=2,
        expected_accessible_max=3,
        expected_accessible_status="needs_local_ordinance_ratio",
    ),
    ParkingCase(
        name="gangnam_entertainment_10000m2_accessible_range_2_to_4",
        pnu="1168011800104170004",
        rule_id="parking_appendix1_row_01",
        metric="facility_area_m2",
        value=10000.0,
        expected_required_spaces=149,
        expected_accessible_min=3,
        expected_accessible_max=6,
        expected_accessible_status="needs_local_ordinance_ratio",
    ),
    ParkingCase(
        name="yongsan_spectator_149_people_one",
        pnu="1117010100100010000",
        rule_id="parking_appendix1_row_06",
        metric="spectator_capacity",
        value=149.0,
        expected_required_spaces=1,
    ),
    ParkingCase(
        name="yongsan_spectator_150_people_two",
        pnu="1117010100100010000",
        rule_id="parking_appendix1_row_06",
        metric="spectator_capacity",
        value=150.0,
        expected_required_spaces=2,
    ),
    ParkingCase(
        name="gangnam_apartment_delegated_external_rule",
        pnu="1168011800104170004",
        rule_id="parking_appendix1_row_05",
        metric="household_or_unit_area",
        value=850.0,
        expected_required_spaces=None,
        expected_status="needs_external_rule",
        expected_accessible_status="needs_external_rule",
    ),
    ParkingCase(
        name="busan_entertainment_99m2_national_fallback_zero",
        pnu="2611010100100010000",
        rule_id="parking_appendix1_row_01",
        metric="facility_area_m2",
        value=99.0,
        expected_required_spaces=0,
    ),
    ParkingCase(
        name="busan_row2_149m2_national_fallback_zero",
        pnu="2611010100100010000",
        rule_id="parking_appendix1_row_02",
        metric="facility_area_m2",
        value=149.0,
        expected_required_spaces=0,
    ),
    ParkingCase(
        name="busan_warehouse_399m2_national_fallback_zero",
        pnu="2611010100100010000",
        rule_id="parking_appendix1_row_08",
        metric="facility_area_m2",
        value=399.0,
        expected_required_spaces=0,
    ),
]


def _round_note6(raw: float) -> int:
    if raw < 1:
        return 0
    whole = math.floor(raw)
    return whole + 1 if raw - whole >= 0.5 else whole


def _jurisdiction_from_pnu(pnu: str) -> dict[str, str]:
    return {
        "sido": pnu[:2],
        "sigungu": pnu[2:5],
        "jurisdiction_code": pnu[:5],
    }


def _load_rules(session) -> dict[str, Any]:
    rows = session.run(
        """
        MATCH (r:ParkingRequirementRule)
        RETURN r.rule_id AS rule_id, properties(r) AS props
        """
    )
    national = {row["rule_id"]: dict(row["props"]) for row in rows}

    local_rows = session.run(
        """
        MATCH (o:LocalOrdinance)-[:HAS_REQUIREMENT_RULE]->(r:LocalParkingRequirementRule)-[:OVERRIDES]->(base:ParkingRequirementRule)
        RETURN o.pnu_prefix AS pnu_prefix,
               base.rule_id AS base_rule_id,
               r.rule_id AS rule_id,
               properties(r) AS props
        ORDER BY size(o.pnu_prefix) DESC, r.rule_id
        """
    )
    local: list[dict[str, Any]] = []
    for row in local_rows:
        props = dict(row["props"])
        props["rule_id"] = row["rule_id"]
        props["base_rule_id"] = row["base_rule_id"]
        props["pnu_prefix"] = row["pnu_prefix"]
        local.append(props)

    return {"national": national, "local": local}


def _prefer_local_rule(base_rule_id: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    preferred_by_base = {
        "parking_appendix1_row_02": "seoul_parking_appendix2_row_02",
        "parking_appendix1_row_11": "seoul_parking_appendix2_row_10_other",
    }
    preferred_id = preferred_by_base.get(base_rule_id)
    if preferred_id:
        for candidate in candidates:
            if candidate.get("rule_id") == preferred_id:
                return candidate
    return candidates[0]


def _select_rule(rules: dict[str, Any], pnu: str, rule_id: str) -> dict[str, Any] | None:
    local_candidates = [
        rule
        for rule in rules["local"]
        if rule.get("pnu_prefix") and pnu.startswith(str(rule["pnu_prefix"]))
        and (rule.get("base_rule_id") == rule_id or rule.get("rule_id") == rule_id)
    ]
    if local_candidates:
        longest = max(len(str(rule["pnu_prefix"])) for rule in local_candidates)
        local_candidates = [rule for rule in local_candidates if len(str(rule["pnu_prefix"])) == longest]
        return _prefer_local_rule(rule_id, local_candidates)
    return rules["national"].get(rule_id)


def calculate_required_spaces(rule: dict[str, Any], metric: str, value: float) -> dict[str, Any]:
    if rule.get("requires_external_rule"):
        return {
            "status": "needs_external_rule",
            "required_spaces": None,
            "reason": rule.get("external_reference"),
        }

    rule_id = rule["rule_id"]
    row_no = str(rule.get("row_no", ""))
    raw: float
    if row_no == "4" or rule_id == "parking_appendix1_row_04":
        if value <= 50:
            raw = value / 100.0
        elif value <= 150:
            raw = 1.0
        else:
            raw = 1.0 + ((value - 150.0) / 100.0)
    elif row_no == "6" or rule_id == "parking_appendix1_row_06":
        if metric == "holes":
            raw = value * 10.0
        elif metric == "bays":
            raw = value
        elif metric == "capacity":
            raw = value / 15.0
        elif metric == "spectator_capacity":
            raw = value / 100.0
        else:
            raise ValueError(f"unsupported row 6 metric: {metric}")
    else:
        spaces_per = rule.get("spaces_per")
        if not spaces_per:
            raise ValueError(f"rule {rule_id} has no spaces_per and no custom calculator")
        raw = value / float(spaces_per)

    return {
        "status": "computed",
        "raw_spaces": raw,
        "required_spaces": _round_note6(raw),
        "rounding_rule": rule.get("rounding_rule"),
    }


def calculate_accessible_spaces(required_spaces: int | None, *,
                                local_rule: dict[str, Any] | None = None,
                                applicable: bool | None = None) -> dict[str, Any]:
    if required_spaces is None:
        return {"status": "needs_external_rule", "accessible_min": None, "accessible_max": None}
    if required_spaces < 10:
        return {"status": "not_applicable_under_10", "accessible_min": 0, "accessible_max": 0}
    if local_rule and local_rule.get("status") == "reviewed":
        ratio = float(local_rule["ratio"])
        if not 0 < ratio <= 1:
            raise ValueError("invalid reviewed accessible parking ratio")
        count = math.ceil(required_spaces * ratio)
        evidence = {"source_appendix": local_rule.get("source_appendix"),
                    "applicability": local_rule.get("applicability"), "ratio": ratio}
        if applicable is True:
            return {**evidence, "status": "computed", "accessible_min": count, "accessible_max": count}
        if applicable is False:
            return {**evidence, "status": "not_applicable_to_facility", "accessible_min": 0, "accessible_max": 0}
        return {**evidence, "status": "needs_facility_applicability", "conditional_spaces": count,
                "accessible_min": None, "accessible_max": None}
    return {
        "status": "needs_local_ordinance_ratio",
        "accessible_min": math.ceil(required_spaces * 0.02),
        "accessible_max": math.ceil(required_spaces * 0.04),
    }


def run_checks(uri: str, user: str, password: str) -> int:
    failures: list[str] = []
    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session() as session:
            rules = _load_rules(session)
            for case in CASES:
                rule = _select_rule(rules, case.pnu, case.rule_id)
                if not rule:
                    print(f"[FAIL] {case.name}: missing rule {case.rule_id}")
                    failures.append(case.name)
                    continue

                calc = calculate_required_spaces(rule, case.metric, case.value)
                accessible = calculate_accessible_spaces(calc["required_spaces"])
                jurisdiction = _jurisdiction_from_pnu(case.pnu)

                ok = (
                    calc["status"] == case.expected_status
                    and calc["required_spaces"] == case.expected_required_spaces
                    and accessible["status"] == case.expected_accessible_status
                    and (
                        case.expected_accessible_min is None
                        or accessible["accessible_min"] == case.expected_accessible_min
                    )
                    and (
                        case.expected_accessible_max is None
                        or accessible["accessible_max"] == case.expected_accessible_max
                    )
                )
                status = "PASS" if ok else "FAIL"
                print(
                    f"[{status}] {case.name}: pnu={case.pnu} jurisdiction={jurisdiction['jurisdiction_code']} "
                    f"rule={case.rule_id} selected={rule.get('rule_id')} metric={case.metric} value={case.value} "
                    f"required={calc['required_spaces']} calc_status={calc['status']} "
                    f"accessible={accessible}"
                )
                if not ok:
                    failures.append(case.name)
    finally:
        driver.close()

    print(f"\nsummary: {len(CASES) - len(failures)}/{len(CASES)} parking cases passed")
    if failures:
        print("failures:", ", ".join(failures))
        return 1
    return 0


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--uri", default=os.getenv("NEO4J_URI", "bolt://localhost:7687"))
    parser.add_argument("--user", default=os.getenv("NEO4J_USER", "neo4j"))
    parser.add_argument("--password", default=os.getenv("NEO4J_PASSWORD", ""))
    args = parser.parse_args()
    return run_checks(args.uri, args.user, args.password)


if __name__ == "__main__":
    raise SystemExit(main())
