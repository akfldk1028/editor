"""Lossless Program v2 review, composing ARR-owned checks without model calls."""
from copy import deepcopy
from datetime import date
from backend.app.modules.law.reference.design_review import review_design_state
from backend.app.modules.law.reference.facility_area_engine import evaluate_facility_areas
from backend.app.modules.law.reference.facility_area_rules import FACILITY_AREA_RULES, bind_snapshot_evidence
import hashlib
import json


def fingerprint(value):
    # The program-law/2 handoff hash: canonical JSON (sorted keys, compact separators,
    # non-ASCII kept), SHA-256. programagent.service.fingerprint is the same contract;
    # both sides must produce this byte-for-byte or request_hash never matches.
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
from backend.app.modules.law.reference.use_research_routes import get_use_research_routes


def review_facilities(facts, assessment_date):
    if not isinstance(facts, list) or any(not isinstance(f, dict) for f in facts):
        raise ValueError("facility_facts must contain objects")
    results = []
    for fact in facts:
        selected = [r for r in FACILITY_AREA_RULES if fact.get("facility_type") in r["facility_types"]]
        bound = bind_snapshot_evidence(fact, selected, assessment_date)
        result = evaluate_facility_areas(bound, selected, assessment_date)
        result.update(facility_type=fact.get("facility_type"), fact_id=fact.get("fact_id"))
        conditions = fact.get("condition_evidence", {})
        if not isinstance(conditions, dict):
            raise ValueError("condition_evidence must be an object")
        for check in result["checks"]:
            rule = next(r for r in selected if r["rule_id"] == check["rule_id"])
            check.update(measurement_scope=rule["measurement_scope"], condition_evidence=deepcopy(conditions))
        results.append(result)
    return results


def review_program(handoff):
    if not isinstance(handoff, dict) or handoff.get("contract_version") != "program-law/2":
        raise ValueError("complete program-law/2 handoff required")
    for field in ("project_id", "program_id", "input_hash", "assessment_date"):
        if not isinstance(handoff.get(field), str) or not handoff[field].strip():
            raise ValueError(f"handoff.{field} required")
    if type(handoff.get("program_revision")) is not int or handoff["program_revision"] < 1:
        raise ValueError("positive program_revision required")
    date.fromisoformat(handoff["assessment_date"])
    if handoff.get("request_hash") != fingerprint({k: v for k, v in handoff.items() if k != "request_hash"}):
        raise ValueError("handoff hash mismatch")
    requirements = handoff.get("requirements", {})
    if not isinstance(requirements, dict) or not isinstance(handoff.get("input_versions"), dict):
        raise ValueError("requirements and input_versions must be objects")
    checks, sources, violations, proposals = [], [], [], []
    facility_results = review_facilities(requirements.get("facility_facts", []), handoff["assessment_date"])
    for result in facility_results:
        checks.append({"check": "facility_area", "result": result})
        for check in result["checks"]:
            if check["status"] == "below_area_minimum":
                violations.append(deepcopy(check))
            if check.get("source"):
                sources.append(deepcopy(check["source"]))
    versions = deepcopy(handoff["input_versions"])
    versions["program"] = handoff.get("content_revision", handoff["program_revision"])
    design = {"assessment_date": handoff["assessment_date"], "versions": versions,
              "facts": requirements.get("legal_facts", []), "review_scopes": ["program"]}
    constraints = requirements.get("legal_constraints", [])
    design_result = review_design_state(design, constraints)
    checks.append({"check": "program_constraints", "result": design_result})
    violations.extend(design_result["violations"])
    sources.extend(design_result["sources"])
    fire_facts = requirements.get("fire_facts", [])
    if not isinstance(fire_facts, list) or any(not isinstance(f, dict) for f in fire_facts):
        raise ValueError("fire_facts must contain scoped fact objects")
    from backend.app.modules.law.reference.fire_requirements import evaluate_fire_requirements
    for fact in fire_facts:
        result = evaluate_fire_requirements(fact, handoff["assessment_date"])
        checks.append({"check": "fire_equipment_requirements", "fact_id": fact.get("fact_id"), "result": result})
        if result.get("source"):
            sources.append(deepcopy(result["source"]))
        for finding in result["findings"]:
            if finding["status"] == "required":
                proposals.append({"kind": "required_equipment", "rule_id": finding["rule_id"],
                    "equipment": finding["equipment"], "scope": finding["required_scope"],
                    "fact_id": fact.get("fact_id"), "review_owner": "systems", "source": result.get("source"),
                    "status": "requires_design_and_installation_review"})
    zoning = requirements.get("zoning_reviews", [])
    if not isinstance(zoning, list):
        raise ValueError("zoning_reviews must be a list")
    use_units = handoff.get("use_units", [])
    for request in zoning:
        if not isinstance(request, dict):
            raise ValueError("zoning review must be an object")
        unit_id = request.get("use_unit_id")
        matches = [u for u in use_units if u.get("use_unit_id") == unit_id]
        if len(matches) != 1:
            raise ValueError("zoning review requires a unique existing use_unit_id")
        from backend.app.modules.land.reference.services.zoning_use_evidence import evaluate_use_evidence
        unit = matches[0]
        # Only explicitly measured statutory area; never borrow the planning ledger.
        area = unit.get("statutory_area") or {}
        measured = (area.get("value") if area.get("unit") == "m2" and area.get("basis") == "statutory_floor_area"
                    and area.get("source_ref") else None)
        classification = request.get("classification", {})
        if not isinstance(classification, dict) or not isinstance(request.get("zone_names", []), list):
            raise ValueError("invalid zoning classification or zone_names")
        result = evaluate_use_evidence({"id": unit_id, "floor_area_m2": measured}, classification,
                                      request.get("zone_names", []), request.get("evidence", {}), handoff["assessment_date"])
        checks.append({"check": "zoning_use_conditions", "use_unit_id": unit_id, "result": result,
                       "permitted": None, "status": "needs_evidence"})
        if result["scoped_rule_result"] in {"prohibit", "conflict"}:
            violations.append({"check": "zoning_use_conditions", "use_unit_id": unit_id, "result": result})
    from backend.app.modules.law.reference.program_parking import review_parking
    parking = review_parking(handoff) if "parking" in handoff.get("requested_checks", []) else None
    if parking is not None:
        checks.append({"check": "parking", "status": parking["status"], "result": parking})
    represented = {"statutory_area_basis": bool(facility_results), "zoning_use_permission": bool(zoning)}
    for requested in handoff.get("requested_checks", []):
        if requested == "parking" and parking is not None:
            continue
        checks.append({"check": requested, "status": "partially_evaluated" if represented.get(requested) else "needs_evidence",
                       "reason": "Individual source-bound checks do not establish complete legal applicability."})
    operations = [requirements.get("operational_type")] + [
        component.get("operational_type") for component in requirements.get("programs", []) if isinstance(component, dict)]
    research_routes = [get_use_research_routes(operational_type=operation)
                       for operation in dict.fromkeys(operations) if isinstance(operation, str) and operation not in {"", "composed"}]
    research_tasks = {}
    for routes in research_routes:
        for source_id, source in routes["sources"].items():
            research_tasks[source_id] = {"source_id": source_id, "source": source,
                "action": "resolve_project_applicability" if source["current_edition_verified"] else "retrieve_current_edition_then_resolve_applicability",
                "required_inputs": source["required_inputs"], "status": "needs_evidence"}
    return {"schema_version": "program-law-review/2", "review_id": "law-v2-" + fingerprint({"handoff": handoff, "checks": checks})[:24],
            "agent": "law", "program_revision": handoff["program_revision"],
            "content_revision": handoff.get("content_revision", handoff["program_revision"]),
            "input_hash": handoff["input_hash"], "input_versions": deepcopy(handoff["input_versions"]),
            "assessment_date": handoff["assessment_date"], "status": "conflict" if violations else "needs_evidence",
            "checks": checks, "sources": sources, "violations": violations, "proposals": proposals,
            "research_routes": research_routes, "research_tasks": list(research_tasks.values()),
            "law_request": deepcopy(handoff), "permit_ready": False, "parking": parking,
            "coverage": {"lossless_program_input": True, "facility_fact_count": len(facility_results),
                         "fire_fact_count": len(fire_facts),
                         "zoning_use_count": len(zoning), "full_permit_review": False}}
