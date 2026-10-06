"""Pass-through endpoints for the Lawagent, which used to import these law.* / design.maas.* owners in-process.

Every view returns the owner function's result unchanged (the agent keeps its own post-processing, e.g. findings),
so only the transport moved: the agent reaches ARR over HTTP, never through sys.path or `manage.py shell`.
Kept out of views.py on purpose: this is the agent seam, not the frontend API. Failures are dicts
({"success": False, "error": ...}) so the agent keeps one shape whatever went wrong.

    POST /law/agent/review-design-state/   {design_state, rules}           -> law.design_review.review_design_state
    POST /law/agent/review-program/        {handoff}                       -> law.program_review.review_program
    POST /law/agent/review-facilities/     {facts, assessment_date}        -> law.program_review.review_facilities
    POST /law/agent/building-uses/         {query?}                        -> law.building_use_catalog.get_building_use_catalog
    POST /law/agent/fire-requirements/     {facts, assessment_date}        -> law.fire_requirements.evaluate_fire_requirements
    POST /law/agent/use-research-routes/   {family_id?, operational_type?} -> law.use_research_routes.get_use_research_routes
    POST /law/agent/ordinance-candidates/  {query, assessment_date, oc?}   -> law.ordinance_discovery.discover_ordinances
    POST /law/agent/parking-design-rules/  {required_spaces, ...options}   -> design.maas.masterplan.rules.parking_design_rules
    POST /law/agent/parking-count/         {zone_names, sigungu_code?, building_type?, floor_area_m2?, program_uses?,
                                            assessment_date?}              -> land.reference.services.regulation_calculator.calculate_all
    POST /law/agent/parcel-limits/         {pnu, building_type?}           -> massv2 legal.load_legal_site + parcel_policy.policy_for
"""
import json
import os
import re

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods


def _body(request):
    try:
        body = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    return body if isinstance(body, dict) else None


def _bad(message):
    return JsonResponse({"success": False, "error": message}, status=400)


def _failed(exc):
    """An owner failure is reported, never turned into a verdict."""
    return JsonResponse({"success": False, "error": f"{type(exc).__name__}: {exc}"}, status=502)


def _reply(value):
    """The owner's return value, verbatim; a non-object is wrapped so the agent always gets an object."""
    if isinstance(value, dict):
        return JsonResponse(value, json_dumps_params={"default": str})
    return JsonResponse({"success": True, "result": value}, json_dumps_params={"default": str}, safe=False)


def _passthrough(request, required, call):
    """Common shape: parse, check the required keys, run the owner, report failure as a dict."""
    body = _body(request)
    if body is None:
        return _bad("Invalid JSON")
    missing = [key for key in required if key not in body]
    if missing:
        return _bad(", ".join(missing) + " required")
    try:
        return _reply(call(body))
    except (TypeError, ValueError) as exc:
        return _bad(str(exc))
    except Exception as exc:
        return _failed(exc)


@csrf_exempt
@require_http_methods(["POST"])
def review_design_state(request):
    from backend.app.modules.law.reference.design_review import review_design_state as owner
    return _passthrough(request, ("design_state", "rules"), lambda b: owner(b["design_state"], b["rules"]))


@csrf_exempt
@require_http_methods(["POST"])
def review_program(request):
    from backend.app.modules.law.reference.program_review import review_program as owner
    return _passthrough(request, ("handoff",), lambda b: owner(b["handoff"]))


@csrf_exempt
@require_http_methods(["POST"])
def review_facilities(request):
    from backend.app.modules.law.reference.program_review import review_facilities as owner
    return _passthrough(request, ("facts", "assessment_date"), lambda b: owner(b["facts"], b["assessment_date"]))


@csrf_exempt
@require_http_methods(["POST"])
def building_uses(request):
    from backend.app.modules.law.reference.building_use_catalog import get_building_use_catalog as owner
    return _passthrough(request, (), lambda b: owner(str(b.get("query") or "")))


@csrf_exempt
@require_http_methods(["POST"])
def fire_requirements(request):
    from backend.app.modules.law.reference.fire_requirements import evaluate_fire_requirements as owner
    return _passthrough(request, ("facts", "assessment_date"), lambda b: owner(b["facts"], b["assessment_date"]))


@csrf_exempt
@require_http_methods(["POST"])
def use_research_routes(request):
    from backend.app.modules.law.reference.use_research_routes import get_use_research_routes as owner
    return _passthrough(request, (), lambda b: owner(str(b.get("family_id") or ""), str(b.get("operational_type") or "")))


@csrf_exempt
@require_http_methods(["POST"])
def ordinance_candidates(request):
    """law.go.kr discovery needs an OC id; the agent sends its own (`oc`), else ARR's LAW_OC environment."""
    from backend.app.modules.law.reference.ordinance_discovery import discover_ordinances as owner

    def call(b):
        oc = b.get("oc") or os.environ.get("LAW_OC")
        if not oc:
            raise ValueError("oc (law.go.kr OC id) required: send it or set LAW_OC for ARR")
        return owner(b["query"], b["assessment_date"], oc)
    return _passthrough(request, ("query", "assessment_date"), call)


_PARKING_OPTIONS = ("facility_type", "parking_method", "structure", "parking_angle", "ramp_shape",
                    "entrance_count", "assessment_date")


@csrf_exempt
@require_http_methods(["POST"])
def parking_design_rules(request):
    """required_spaces is an already resolved legal count (rounding belongs to the parking-requirement calculator)."""
    from backend.app.modules.design.generation.maas.masterplan.rules import parking_design_rules as owner

    def call(b):
        options = {k: b[k] for k in _PARKING_OPTIONS if k in b}
        return owner(int(b["required_spaces"]), **options)
    return _passthrough(request, ("required_spaces",), call)


_PARKING_COUNT_INPUTS = ("sigungu_code", "building_type", "floor_area_m2", "program_uses", "assessment_date")


@csrf_exempt
@require_http_methods(["POST"])
def parking_count(request):
    """The binding 부설주차장 count for one programme, verbatim from the single numeric owner.
    Lawagent's golden set (scripts/verify_parking_counts.py) compares its recorded answers against this."""
    from backend.app.modules.land.reference.services import regulation_calculator as owner

    def call(b):
        zones = b["zone_names"]
        if not isinstance(zones, list) or not all(isinstance(z, str) for z in zones):
            raise ValueError("zone_names must be a list of strings")
        inputs = {k: b[k] for k in _PARKING_COUNT_INPUTS if b.get(k) is not None}
        return owner.calculate_all(zones, use_llm_extraction=False, **inputs)
    return _passthrough(request, ("zone_names",), call)


def ordinance_receipt(regulation):
    """Which articles and which ordinance edition the caps came from, on which assessment date."""
    if not regulation:
        return {"status": "needs_evidence", "missing_evidence": ["regulation_receipt"]}
    coverage = regulation.get("municipal_coverage") or {}
    return {
        "status": coverage.get("status"),
        "assessment_date": regulation.get("assessment_date"),
        "bcr_pct": regulation.get("bcr_pct"), "bcr_article": regulation.get("bcr_article"),
        "far_pct": regulation.get("far_pct"), "far_article": regulation.get("far_article"),
        "height_limit_m": regulation.get("height_limit_m"), "height_article": regulation.get("height_article"),
        "height_status": regulation.get("height_status"),
        "height_missing_evidence": regulation.get("height_missing_evidence"),
        "height_overlays": regulation.get("height_overlays"),
        "national_bcr_ceiling_pct": regulation.get("national_bcr_ceiling_pct"),
        "national_far_ceiling_pct": regulation.get("national_far_ceiling_pct"),
        "municipal_coverage": {key: coverage.get(key) for key in
                               ("status", "caps_complete", "sources", "excluded_sources", "missing_evidence", "limitations")},
    }


@csrf_exempt
@require_http_methods(["POST"])
def parcel_limits(request):
    """Statutory caps for one parcel by massv2 (legal + parcel_policy): the same figures the numeric gate uses.
    The output shape is the one the agent's former `manage.py shell` snippet produced, field for field."""
    body = _body(request)
    if body is None:
        return _bad("Invalid JSON")
    pnu = str(body.get("pnu") or "")
    if not re.fullmatch(r"[0-9]{19}", pnu):
        return _bad("PNU must contain exactly 19 ASCII digits")
    building_type = str(body.get("building_type") or "업무시설")
    try:
        from backend.app.modules.design.generation.maas.massv2.legal import load_legal_site
        from backend.app.modules.design.generation.maas.massv2.parcel_policy import policy_for
        site = load_legal_site(pnu, building_type=building_type)
    except Exception as exc:
        return _failed(exc)
    parcel_area = float(site.parcel_area_m2)
    out = {"success": True, "pnu": pnu, "building_type": building_type,
           "parcel_area_m2": round(parcel_area, 3),
           "ground_capacity_m2": round(float(site.ground_capacity_m2), 3),
           "far_capacity_m2": round(float(site.far_capacity_m2), 3),
           "max_storeys": site.max_storeys,
           "bcr_pct": round(100 * float(site.ground_capacity_m2) / parcel_area, 2),
           "far_pct": round(100 * float(site.far_capacity_m2) / parcel_area, 2)}
    try:
        policy = policy_for(pnu)
        out["policy"] = policy if isinstance(policy, dict) else (
            {k: getattr(policy, k) for k in dir(policy) if not k.startswith("_") and not callable(getattr(policy, k))}
            or repr(policy))
    except Exception as exc:
        out["policy_error"] = str(exc)
    try:
        out["evidence"] = site.evidence()
    except Exception as exc:
        out["evidence"] = {"error": str(exc)}
    out["ordinance"] = ordinance_receipt(site.regulation)
    if site.regulation:
        out["zones"] = site.regulation.get("matched_zones")
    return JsonResponse(out, json_dumps_params={"default": str, "ensure_ascii": False})


@csrf_exempt
@require_http_methods(["POST"])
def facility_criteria(request):
    """Expose the existing owner registry, including its pinned source editions."""
    from copy import deepcopy
    from backend.app.modules.law.reference.facility_area_rules import FACILITY_AREA_RULES

    def call(body):
        facility_type = body.get("facility_type", "")
        if not isinstance(facility_type, str):
            raise ValueError("facility_type must be a string")
        return {"rules": deepcopy([rule for rule in FACILITY_AREA_RULES
                                  if not facility_type or facility_type in rule["facility_types"]]),
                "facility_types": sorted({kind for rule in FACILITY_AREA_RULES for kind in rule["facility_types"]}),
                "permit_ready": False}
    return _passthrough(request, (), call)
