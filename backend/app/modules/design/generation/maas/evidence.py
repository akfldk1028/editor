"""MAAS evidence bundle exporter.

This module builds the canonical review packet for one saved MAAS candidate.
It does not perform new legal calculations; unknown or unavailable domains are
kept as ``needs_evidence`` so downstream agents cannot mistake absence for pass.
"""

from __future__ import annotations

from typing import Any

from django.utils import timezone

from backend.app.modules.design.generation.maas.law_provenance import build_law_provenance_projection
from backend.app.modules.design.generation.maas.parking_layout import evaluate_small_attached_parking_relief


SCHEMA_VERSION = "arr.maas.evidence.v0"


def _constraint_limit(constraints: list[dict[str, Any]], name: str) -> float | None:
    for constraint in constraints or []:
        if constraint.get("name") != name:
            continue
        value = constraint.get("val")
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _metric(props: dict[str, Any], *names: str) -> float | None:
    for name in names:
        value = props.get(name)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _limit_check(
    *,
    key: str,
    label: str,
    provided_value: float | None,
    required_value: float | None,
    unit: str,
    requirement: str = "max",
    evidence_refs: list[str] | None = None,
) -> dict[str, Any]:
    if provided_value is None or required_value is None:
        status = "needs_evidence"
        warnings = [f"{label} provided or required value is missing."]
    elif requirement == "min":
        status = "pass" if provided_value + 1e-9 >= required_value else "fail"
        warnings = []
    else:
        status = "pass" if provided_value <= required_value + 1e-9 else "fail"
        warnings = []

    return {
        "id": f"check:{key}",
        "key": key,
        "domain": "bulk_and_density" if key.startswith("bulk_and_density") else "building_line_and_setbacks",
        "label": label,
        "status": status,
        "severity": "hard",
        "source": "arr",
        "basis": {"law_articles": [], "formula": None, "rule_text": ""},
        "required": {"value": required_value, "unit": unit, "requirement": requirement},
        "provided": {"value": provided_value, "unit": unit},
        "object_refs": [],
        "evidence_refs": evidence_refs or [],
        "warnings": warnings,
        "errors": [],
    }


def _needs_evidence_check(
    key: str,
    *,
    domain: str,
    label: str,
    severity: str = "hard",
    rule_text: str = "",
    law_articles: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": f"check:{key}",
        "key": key,
        "domain": domain,
        "label": label,
        "status": "needs_evidence",
        "severity": severity,
        "source": "arr",
        "basis": {
            "law_articles": law_articles or [],
            "formula": None,
            "rule_text": rule_text,
        },
        "required": {},
        "provided": {},
        "object_refs": [],
        "evidence_refs": [],
        "warnings": [],
        "errors": [],
    }


def _apply_parking_check(checks: list[dict[str, Any]], parking_precheck: dict[str, Any]) -> None:
    check = next((item for item in checks if item.get("key") == "parking_loading_and_mobility.parking_required_count"), None)
    if not check:
        return
    required_count = parking_precheck.get("required_count") if isinstance(parking_precheck.get("required_count"), dict) else {}
    layout = parking_precheck.get("layout_candidate") if isinstance(parking_precheck.get("layout_candidate"), dict) else {}
    required_spaces = required_count.get("required_spaces")
    provided_spaces = layout.get("provided_spaces")
    if isinstance(required_spaces, int):
        check["status"] = "pass" if layout.get("status") == "pass" and (provided_spaces or 0) >= required_spaces else "needs_evidence"
        check["severity"] = "hard"
        check["required"] = {
            "parking_spaces": required_spaces,
            "accessible": required_count.get("accessible") or {},
        }
        check["provided"] = {
            "layout_status": layout.get("status"),
            "provided_spaces": provided_spaces,
            "provided_accessible_spaces": layout.get("provided_accessible_spaces"),
            "placement_mode": layout.get("placement_mode"),
            "unmet_spaces": layout.get("unmet_spaces"),
        }
        check["basis"]["formula"] = required_count.get("rounding_rule")
        check["basis"]["rule_text"] = "Required count resolved from Graph DB parking law/ordinance rules; layout is a deterministic MAAS precheck, not final construction documentation."
        check["evidence_refs"].append("evidence:parking_precheck")
        if check["status"] != "pass":
            check["warnings"].append("Parking count is computed, but detailed layout feasibility still needs solver/authority review.")
    elif required_count.get("status") == "needs_external_rule":
        check["status"] = "needs_evidence"
        check["provided"] = {"calculation_status": "needs_external_rule", "reason": required_count.get("reason")}


def _parking_status(parking_precheck: dict[str, Any]) -> str:
    required_count = parking_precheck.get("required_count") if isinstance(parking_precheck.get("required_count"), dict) else {}
    layout = parking_precheck.get("layout_candidate") if isinstance(parking_precheck.get("layout_candidate"), dict) else {}
    if isinstance(required_count.get("required_spaces"), int) and layout.get("status") == "pass":
        return "precheck_pass"
    if isinstance(required_count.get("required_spaces"), int):
        return "needs_layout_evidence"
    return "needs_evidence"


def _issue(issue_id: str, *, title: str, check_refs: list[str], description: str = "", assignee: str = "final_judge") -> dict[str, Any]:
    return {
        "id": issue_id,
        "topic_type": "missing_evidence",
        "severity": "hard",
        "title": title,
        "description": description,
        "status": "open",
        "check_refs": check_refs,
        "asset_refs": [],
        "assignee": assignee,
    }


def _safe_geojson(value: dict[str, Any] | None, fallback_type: str = "Feature") -> dict[str, Any]:
    if isinstance(value, dict) and isinstance(value.get("type"), str):
        return value
    if fallback_type == "Feature":
        return {"type": "Feature", "properties": {}, "geometry": None}
    return {"type": "FeatureCollection", "features": []}


def _min_floor_plate_area(floor_plates: list[Any]) -> float | None:
    areas = [
        float(plate.get("area_m2"))
        for plate in floor_plates
        if isinstance(plate, dict) and isinstance(plate.get("area_m2"), (int, float))
    ]
    return min(areas) if areas else None


def _saved_shape_signature_3d(
    *,
    props: dict[str, Any],
    floor_plates: list[Any],
    mass_volumes: list[Any],
) -> dict[str, Any]:
    plate_areas = [
        round(float(plate.get("area") or plate.get("area_m2") or 0.0), 2)
        for plate in floor_plates
        if isinstance(plate, dict)
    ]
    volume_profile = []
    for volume in mass_volumes:
        if not isinstance(volume, dict):
            continue
        volume_profile.append({
            "bottom_height": volume.get("bottom_height"),
            "top_height": volume.get("top_height"),
            "area_m2": volume.get("area_m2") or volume.get("area"),
        })
    return {
        "height_m": props.get("height"),
        "num_floors": props.get("num_floors"),
        "volume_count": len(volume_profile) if volume_profile else (1 if props.get("height") else 0),
        "volume_profile": volume_profile,
        "floor_plate_count": len(plate_areas),
        "floor_plate_area_profile": plate_areas,
    }


def _saved_diversity_summary(props: dict[str, Any], signature_3d: dict[str, Any]) -> dict[str, Any] | None:
    existing = props.get("candidate_diversity")
    if isinstance(existing, dict):
        return existing
    if props.get("diversity_score") is None and props.get("source_iou") is None and not signature_3d:
        return None
    footprint_diversity = props.get("diversity_score")
    try:
        footprint_value = float(footprint_diversity or 0.0)
    except (TypeError, ValueError):
        footprint_value = 0.0
    if footprint_value >= 0.2:
        diversity_class = "plan_diverse"
    elif int(signature_3d.get("volume_count") or 0) > 1 or int(signature_3d.get("floor_plate_count") or 0) > 0:
        diversity_class = "section_diverse"
    else:
        diversity_class = "near_duplicate"
    return {
        "class": diversity_class,
        "footprint_diversity_score": footprint_diversity,
        "source_iou": props.get("source_iou"),
        "shape_signature_3d": signature_3d,
    }


def build_maas_evidence_bundle(
    *,
    job: Any,
    design: Any,
    asset_refs: dict[str, Any] | None = None,
    generated_at: Any | None = None,
) -> dict[str, Any]:
    """Build an ``arr.maas.evidence.v0`` bundle for one saved design result."""
    created_at = (generated_at or timezone.now()).isoformat().replace("+00:00", "Z")
    constraints = job.constraints or []
    job_spec = job.job_spec or {}
    options = job_spec.get("options") if isinstance(job_spec.get("options"), dict) else {}
    building_type = options.get("building_type") or "unknown"
    mass_geojson = _safe_geojson(design.mass_geojson)
    props = mass_geojson.get("properties") or {}
    maas_model = props.get("maas_model") if isinstance(props.get("maas_model"), dict) else {}
    legal_metrics = maas_model.get("legal_metrics") if isinstance(maas_model.get("legal_metrics"), dict) else {}
    pnu = job.pnu or None
    sigungu_code = pnu[:5] if pnu else None

    bcr_value = _first_present(_metric(props, "bcr"), _metric(legal_metrics, "bcr"))
    far_value = _first_present(_metric(props, "far"), _metric(legal_metrics, "far"))
    height_value = _first_present(_metric(props, "height"), _metric(legal_metrics, "height"))
    min_setback_value = _first_present(_metric(props, "min_setback"), _metric(legal_metrics, "min_setback"))
    bcr_limit = _constraint_limit(constraints, "bcr")
    far_limit = _constraint_limit(constraints, "far")
    height_limit = _constraint_limit(constraints, "height")
    setback_limit = _constraint_limit(constraints, "setback")

    candidate_ref = f"candidate:{props.get('variant_id') or design.design_id}"
    metric_evidence_ref = "evidence:mass_metrics"
    checks = [
        _limit_check(
            key="bulk_and_density.bcr",
            label="건폐율",
            provided_value=bcr_value,
            required_value=bcr_limit,
            unit="%",
            evidence_refs=[metric_evidence_ref],
        ),
        _limit_check(
            key="bulk_and_density.far",
            label="용적률",
            provided_value=far_value,
            required_value=far_limit,
            unit="%",
            evidence_refs=[metric_evidence_ref],
        ),
        _limit_check(
            key="bulk_and_density.height",
            label="높이",
            provided_value=height_value,
            required_value=height_limit,
            unit="m",
            evidence_refs=[metric_evidence_ref],
        ),
        _limit_check(
            key="building_line_and_setbacks.adjacent_setback",
            label="인접대지 이격",
            provided_value=min_setback_value,
            required_value=setback_limit,
            unit="m",
            requirement="min",
            evidence_refs=[metric_evidence_ref],
        ),
        _needs_evidence_check(
            "zoning_and_land_use.allowed_by_zone",
            domain="zoning_and_land_use",
            label="용도지역별 허용용도",
        ),
        _needs_evidence_check(
            "parking_loading_and_mobility.parking_required_count",
            domain="parking_loading_and_mobility",
            label="주차대수",
            rule_text="Parking rule text alone is not enough for pass.",
            law_articles=["주차장법 시행령 별표1"],
        ),
        _needs_evidence_check(
            "model_documents_and_artifacts.vworld_visual_check",
            domain="model_documents_and_artifacts",
            label="VWorld/Cesium 실브라우저 배치 확인",
        ),
    ]
    if pnu is None:
        checks.insert(
            0,
            _needs_evidence_check(
                "site_rights_and_cadastre.pnu_identity",
                domain="site_rights_and_cadastre",
                label="PNU 필지 식별자",
                rule_text="Canonical evidence must not synthesize a fake PNU.",
            ),
        )
    for check in checks:
        check.setdefault("object_refs", []).append(candidate_ref)

    law_projection = build_law_provenance_projection()
    refs_by_check = law_projection.get("refs_by_check") if isinstance(law_projection, dict) else {}
    if isinstance(refs_by_check, dict):
        for check in checks:
            law_refs = refs_by_check.get(check["key"]) or []
            if not law_refs:
                continue
            basis = check.setdefault("basis", {})
            existing_refs = basis.setdefault("law_articles", [])
            for ref in law_refs:
                if ref not in existing_refs:
                    existing_refs.append(ref)
                if ref not in check["evidence_refs"]:
                    check["evidence_refs"].append(ref)

    hard_failures: list[str] = []
    missing_evidence: list[str] = []
    overall_status = "needs_evidence"

    issues = [
        *(
            [
                _issue(
                    "issue:site:missing-pnu",
                    title="PNU 필지 식별자 누락",
                    description="No PNU is available for this job. Do not substitute a placeholder parcel number.",
                    check_refs=["check:site_rights_and_cadastre.pnu_identity"],
                    assignee="site_reviewer",
                )
            ]
            if pnu is None
            else []
        ),
        _issue(
            "issue:zoning:missing-use-allowance",
            title="용도지역별 허용용도 검토 미완료",
            description="Requested use has not been checked against zoning, overlays, district unit plan, and ordinance tables.",
            check_refs=["check:zoning_and_land_use.allowed_by_zone"],
            assignee="law_reviewer",
        ),
        _issue(
            "issue:parking:missing-count",
            title="주차대수 산정 미완료",
            description="Required/provided parking count and layout feasibility are not computed.",
            check_refs=["check:parking_loading_and_mobility.parking_required_count"],
            assignee="mobility_reviewer",
        ),
        _issue(
            "issue:vworld:missing-real-browser-check",
            title="VWorld 실브라우저 배치 확인 미완료",
            description="Headless/API checks do not prove final Cesium/VWorld placement.",
            check_refs=["check:model_documents_and_artifacts.vworld_visual_check"],
            assignee="visual_qa_reviewer",
        ),
    ]

    floor_plates = props.get("floor_plates") or maas_model.get("floor_plates") or []
    floor_groups = props.get("floor_groups") or maas_model.get("floor_groups") or []
    mass_volumes = props.get("mass_volumes") or maas_model.get("volumes") or []
    parking_precheck = props.get("parking_precheck") or maas_model.get("parking_precheck") or {}
    if not isinstance(parking_precheck, dict):
        parking_precheck = {}
    if "small_attached_parking_relief" not in parking_precheck:
        parking_precheck = {
            **parking_precheck,
            "small_attached_parking_relief": evaluate_small_attached_parking_relief(
                road_context=props.get("road_context") or props.get("parking_road_context")
            ),
        }
    parking_strategy = props.get("parking_strategy") or maas_model.get("parking_strategy")
    _apply_parking_check(checks, parking_precheck)
    parking_status = _parking_status(parking_precheck)
    if parking_status != "needs_evidence":
        issues = [
            issue for issue in issues
            if "check:parking_loading_and_mobility.parking_required_count" not in issue.get("check_refs", [])
        ]
    hard_failures = [check["key"] for check in checks if check["status"] == "fail" and check["severity"] == "hard"]
    missing_evidence = [check["key"] for check in checks if check["status"] in {"needs_evidence", "unknown"}]
    overall_status = "fail" if hard_failures else ("needs_evidence" if missing_evidence else "pass")
    signature_3d = props.get("shape_signature_3d")
    if not isinstance(signature_3d, dict) or not signature_3d:
        signature_3d = _saved_shape_signature_3d(
            props=props,
            floor_plates=floor_plates,
            mass_volumes=mass_volumes,
        )
    diversity_summary = _saved_diversity_summary(props, signature_3d)

    return {
        "schema_version": SCHEMA_VERSION,
        "bundle_id": f"maas-evidence:{job.id}:{design.design_id}",
        "created_at": created_at,
        "source": {
            "system": "ARR",
            "algorithm": props.get("algorithm") or "maas_legal_envelope",
            "generator_version": None,
            "git_sha": None,
        },
        "project": {
            "project_id": None,
            "review_stage": "precheck",
            "application_type": "new_construction",
            "jurisdiction": {"country": "KR", "sigungu_code": sigungu_code},
            "applicant": {},
            "review_scope": {
                "mass_only": True,
                "includes_floor_plan": bool(floor_groups),
                "includes_parking_layout": bool(parking_precheck.get("layout_candidate")),
                "includes_fire_strategy": False,
                "includes_energy": False,
                "includes_structural": False,
            },
            "assumptions": ["Evidence bundle generated from saved ARR MAAS result."],
            "exclusions": ["Detailed parking, fire, structural, energy, and MEP design are not computed."],
        },
        "site": {
            "pnu": pnu,
            "address": job.address or None,
            "site_area_m2": job.site_area_m2,
            "site_polygon": _safe_geojson(job.site_polygon, fallback_type="FeatureCollection"),
            "administrative_codes": {"sigungu_code": sigungu_code},
            "zones": [],
            "matched_zones": [],
            "unmatched_zones": [],
            "overlay_zones": [],
            "district_unit_plan": {"applies": None, "plan_id": None, "evidence_refs": []},
            "land_info": {
                "land_area_m2": job.site_area_m2,
                "land_use": None,
                "official_land_price": None,
                "land_category": None,
                "land_use_situation": None,
            },
            "road_frontages": [],
            "neighbor_parcels": [],
        },
        "candidate": {
            "job_id": str(job.id),
            "design_id": design.design_id,
            "candidate_id": str(props.get("variant_id") or design.design_id),
            "variant_id": props.get("variant_id"),
            "mass_shape": props.get("mass_shape"),
            "maas_concept": props.get("maas_concept"),
            "intended_use": {
                "building_type": building_type,
                "primary_use": building_type if building_type != "unknown" else None,
                "secondary_uses": [],
                "use_classification": None,
                "units": None,
                "households": None,
                "occupancy_assumption": None,
            },
            "score": _first_present(props.get("maas_score"), design.ranking),
            "parking_strategy": parking_strategy,
            "parking_strategy_candidates": props.get("parking_strategy_candidates") or [],
            "parking_precheck": parking_precheck,
            "diversity": diversity_summary,
            "rank": design.ranking,
            "is_pareto_optimal": design.is_pareto_optimal,
            "is_feasible": design.is_feasible,
            "objectives": design.outputs or {},
            "repair_actions": props.get("notes") or [],
            "rejected_siblings": [],
        },
        "geometry": {
            "crs": "EPSG:4326",
            "mass_geojson": mass_geojson,
            "bbox": [],
            "floor_plates": floor_plates,
            "floor_groups": floor_groups,
            "mass_volumes": mass_volumes,
            "maas_model": maas_model,
            "verb_sequence": props.get("maas_verb_sequence") or maas_model.get("verb_sequence") or [],
            "geometry_metrics": {
                "height_m": height_value,
                "num_floors": _first_present(props.get("num_floors"), legal_metrics.get("num_floors")),
                "floor_height_m": props.get("floor_height"),
                "footprint_area_m2": _first_present(props.get("footprint_area"), legal_metrics.get("footprint_area")),
                "total_floor_area_m2": _first_present(props.get("floor_area"), legal_metrics.get("floor_area")),
                "min_floor_plate_area_m2": _min_floor_plate_area(floor_plates),
                "min_setback_m": min_setback_value,
                "open_space_pct": props.get("open_pct"),
                "shape_signature": props.get("shape_signature") or "",
                "shape_signature_3d": signature_3d,
            },
        },
        "legal": {
            "summary": {"status": overall_status, "hard_failures": hard_failures, "warnings": []},
            "limits": {"bcr_pct": bcr_limit, "far_pct": far_limit, "height_limit_m": height_limit},
            "metrics": {"bcr_pct": bcr_value, "far_pct": far_value, "height_m": height_value},
            "datum": {},
            "setbacks": {"adjacent_setback_m": setback_limit, "min_setback_m": min_setback_value},
            "sunlight": {},
            "daylight_spacing": {},
            "road_building_line": {},
            "corner_cutoff": {},
            "landscaping": {},
            "building_use": {},
            "site_road_requirement": {},
            "split_zoning": {},
            "use_classification": {
                "requested_use": building_type if building_type != "unknown" else None,
                "normalized_use": building_type if building_type != "unknown" else None,
                "allowed": None,
                "prohibited": None,
                "conditional": None,
                "requires_discretionary_review": None,
                "basis": {"zone_tables": [], "ordinance_refs": [], "law_articles": []},
                "evidence_refs": [],
            },
            "ordinance_overrides": [],
            "law_articles": law_projection.get("articles", []) if isinstance(law_projection, dict) else [],
            "extended_regulations": {},
            "graph_projection": law_projection.get("graph_status", {}) if isinstance(law_projection, dict) else {},
        },
        "program": {
            "building_type": building_type,
            "program_packing": [
                g.get("program_packing") for g in floor_groups if isinstance(g, dict) and g.get("program_packing")
            ],
            "core": {"status": "needs_evidence"},
            "usable_depth": {},
            "egress_precheck": {},
            "floor_plate_viability": [],
        },
        "mobility": {
            "parking": {
                "status": parking_status,
                "strategy": parking_strategy,
                "precheck": parking_precheck,
                "reason": (
                    "Graph DB required parking count and deterministic layout precheck are attached."
                    if parking_status != "needs_evidence"
                    else "Parking strategy is recorded for mass-generation repair, but required count and layout feasibility are not computed yet."
                ),
            },
            "access": {"status": "needs_evidence"},
        },
        "life_safety": {
            "fire": {"status": "needs_evidence"},
            "evacuation": {"status": "needs_evidence"},
            "structural_safety": {"status": "needs_evidence"},
            "elevator": {"status": "needs_evidence"},
            "accessibility": {"status": "needs_evidence"},
            "finishing_materials": {"status": "needs_evidence"},
        },
        "environment": {
            "energy_saving": {"status": "needs_evidence"},
            "room_daylighting_ventilation": {"status": "needs_evidence"},
            "sewage_treatment": {"status": "needs_evidence"},
            "building_systems": {"status": "needs_evidence"},
            "cpted": {"status": "needs_evidence"},
            "public_open_space": {"status": "needs_evidence"},
            "infrastructure_fee": {"status": "needs_evidence"},
        },
        "checks": checks,
        "issues": issues,
        "validators": {"overall_status": overall_status, "runs": []},
        "assets": asset_refs or {},
        "provenance": {
            "entities": [
                {"id": candidate_ref, "type": "MassCandidate"},
                {"id": "evidence:mass_metrics", "type": "MetricEvidence"},
            ]
            + (law_projection.get("provenance_entities", []) if isinstance(law_projection, dict) else []),
            "activities": [{"id": "activity:build_maas_evidence_bundle", "type": "EvidenceExport"}],
            "agents": [{"id": "agent:arr", "type": "SoftwareAgent"}],
            "relations": [
                {"type": "wasGeneratedBy", "entity": candidate_ref, "activity": "activity:build_maas_evidence_bundle"}
            ]
            + (law_projection.get("provenance_relations", []) if isinstance(law_projection, dict) else []),
        },
        "agent_reviews": [],
        "final_decision": {
            "status": overall_status,
            "decided_by": None,
            "blocking_failures": hard_failures,
            "missing_evidence": missing_evidence,
            "accepted_risks": [],
            "summary": "Evidence bundle generated structurally; final legal pass requires all hard checks and missing evidence to be resolved.",
        },
    }


__all__ = ["SCHEMA_VERSION", "build_maas_evidence_bundle"]
