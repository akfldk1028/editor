"""
Regulation Validator — generation-verification loop for building mass.

Validates GA-optimized designs against building regulations (BCR, FAR, height, setback).
When violations are found, tightens constraints and re-runs optimization (max 3 retries).

Pattern: Harness "generation-verification" (매스 생성 → 법규 에이전트 검증 → 재생성).
"""

import logging

logger = logging.getLogger(__name__)

# Margin added when tightening a violated constraint (e.g., 5% below the limit)
_TIGHTEN_MARGIN = 0.05


def validate_design(design_metrics: dict, regulation_result: dict) -> list[dict]:
    """
    Compare a single design's metrics against regulation limits.

    Args:
        design_metrics: dict with keys bcr, far, height, min_setback (from mass_evaluator)
        regulation_result: dict from regulation_calculator.calculate_all()

    Returns:
        List of violation dicts: [{type, actual, limit, severity, message}]
        Empty list means the design passes all checks.
    """
    violations = []

    # BCR check
    bcr_limit = regulation_result.get("bcr_pct")
    bcr_actual = design_metrics.get("bcr", 0)
    if bcr_limit is not None and bcr_actual > bcr_limit:
        violations.append({
            "type": "bcr",
            "actual": bcr_actual,
            "limit": bcr_limit,
            "severity": _severity(bcr_actual, bcr_limit),
            "message": f"건폐율 {bcr_actual:.1f}% > 한도 {bcr_limit}%",
        })

    # FAR check
    far_limit = regulation_result.get("far_pct")
    far_actual = design_metrics.get("far", 0)
    if far_limit is not None and far_actual > far_limit:
        violations.append({
            "type": "far",
            "actual": far_actual,
            "limit": far_limit,
            "severity": _severity(far_actual, far_limit),
            "message": f"용적률 {far_actual:.1f}% > 한도 {far_limit}%",
        })

    # Height check
    height_limit = regulation_result.get("height_limit_m")
    height_actual = design_metrics.get("height", 0)
    if height_limit is not None and height_actual > height_limit:
        violations.append({
            "type": "height",
            "actual": height_actual,
            "limit": height_limit,
            "severity": _severity(height_actual, height_limit),
            "message": f"높이 {height_actual:.1f}m > 한도 {height_limit}m",
        })

    # Setback check (must be >= limit, so violation when actual < limit)
    setback_limit = regulation_result.get("adjacent_setback_m")
    setback_actual = design_metrics.get("min_setback", 0)
    if setback_limit is not None and setback_actual < setback_limit:
        violations.append({
            "type": "setback",
            "actual": setback_actual,
            "limit": setback_limit,
            "severity": _severity(setback_limit, setback_actual),
            "message": f"이격거리 {setback_actual:.1f}m < 한도 {setback_limit}m",
        })

    return violations


def auto_correct_constraints(violations: list[dict], constraints: list[dict]) -> list[dict]:
    """
    Tighten constraint values based on violations.

    For each violation, finds the matching constraint and adjusts:
    - "Less than" constraints: reduce val by margin (e.g., BCR 60 → 57)
    - "Greater than" constraints: increase val by margin (e.g., setback 0.5 → 0.55)

    Args:
        violations: output from validate_design()
        constraints: current job_spec constraints (mutated in place)

    Returns:
        Updated constraints list (same object, modified in place).
    """
    violation_map = {v["type"]: v for v in violations}

    for c in constraints:
        name = c.get("name", "")
        v = violation_map.get(name)
        if not v:
            continue

        old_val = c["val"]
        req = c.get("Requirement", "")

        if req == "Less than":
            # Tighten downward: e.g., BCR 60 → 60 * (1 - margin) = 57
            c["val"] = round(old_val * (1 - _TIGHTEN_MARGIN), 2)
        elif req == "Greater than":
            # Tighten upward: e.g., setback 0.5 → 0.5 * (1 + margin) = 0.525
            c["val"] = round(old_val * (1 + _TIGHTEN_MARGIN), 2)

        logger.info(
            "Constraint '%s' tightened: %s → %s (violation: actual=%s, limit=%s)",
            name, old_val, c["val"], v["actual"], v["limit"],
        )

    return constraints


def validate_best_designs(designs_metrics: list[dict], regulation_result: dict,
                          top_n: int = 3) -> dict:
    """
    Validate the top N designs from a GA run.

    Args:
        designs_metrics: list of dicts with bcr, far, height, min_setback
        regulation_result: from regulation_calculator.calculate_all()
        top_n: how many top designs to check

    Returns:
        {
            "all_valid": bool,
            "violations": [list per design],
            "worst_violations": [aggregated unique violations across all],
        }
    """
    all_violations = []
    worst = {}

    for metrics in designs_metrics[:top_n]:
        v = validate_design(metrics, regulation_result)
        all_violations.append(v)
        for item in v:
            key = item["type"]
            if key not in worst or item["severity"] > worst[key]["severity"]:
                worst[key] = item

    return {
        "all_valid": all(len(v) == 0 for v in all_violations),
        "violations": all_violations,
        "worst_violations": list(worst.values()),
    }


def _severity(actual: float, limit: float) -> str:
    """Classify violation severity based on how much actual exceeds limit."""
    if limit == 0:
        return "critical"
    ratio = abs(actual - limit) / abs(limit)
    if ratio > 0.2:
        return "critical"
    if ratio > 0.1:
        return "major"
    return "minor"
