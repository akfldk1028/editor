"""Deterministic cross-program MAAS benchmark with a clean PNG artifact."""

from __future__ import annotations

import json
import tempfile
from copy import deepcopy
from pathlib import Path
from statistics import mean
from typing import Any

from PIL import Image, ImageDraw, ImageFont
from shapely.affinity import rotate
from shapely.geometry import Polygon, box, mapping, shape

from backend.app.modules.design.generation.maas.preference.loop import feature_preview_png
from backend.app.modules.design.generation.maas.llm_proposals import build_site_context
from backend.app.modules.design.generation.maas.source_geometry import compile_sequence_to_source_mass
from backend.app.modules.design.generation.maas.program_massing.profiles import resolve_program_profile
from backend.app.modules.design.generation.maas.program_massing.creative import attach_creative_mass_evidence, creative_seed_sequences
from backend.app.modules.design.generation.maas.program_massing.sequences import program_seed_sequences
from backend.app.modules.design.generation.maas.program_massing.search import _descriptor_distance, _feature, search_creative_elites, search_program_elites


PROGRAM_CASES = (
    ("근린생활시설", "neighborhood_living", 15.0, 5),
    ("체육관", "gymnasium", 12.0, 2),
)


def run_program_massing_benchmark(*, output_json: Path, output_png: Path) -> dict[str, Any]:
    base = box(0, 0, 60, 40)
    rows: list[dict[str, Any]] = []
    features: list[dict[str, Any]] = []
    search_reports: dict[str, Any] = {}
    for building_type, expected_profile, height, floors in PROGRAM_CASES:
        profile = resolve_program_profile(building_type)
        elites, search_report = search_program_elites(base, building_type=building_type, height=height, floors=floors)
        search_reports[profile["id"]] = search_report
        for elite in elites:
            sequence, source, feature = elite.sequence, elite.source, elite.feature
            evidence = feature["properties"]["program_massing_evidence"]
            rows.append({
                "building_type": building_type,
                "profile_id": profile["id"],
                "expected_profile": expected_profile,
                "sequence": sequence.name,
                "verbs": [item.verb for item in sequence.calls],
                "family": source.signature().get("family"),
                "volume_count": len(source.volumes),
                "surface_count": int(source.signature().get("effective_surface_count") or len(source.surfaces)),
                "raw_surface_count": len(source.surfaces),
                "footprint_area_ratio": round(source.footprint.area / base.area, 3),
                "program_fit_score": evidence["program_fit_score"],
                "program_hard_pass": evidence["hard_pass"],
                "architectural_score": feature["properties"]["program_spatial_evidence"]["architectural_score"],
            })
            features.append(feature)
    profile_groups = {
        profile_id: [row for row in rows if row["profile_id"] == profile_id]
        for profile_id in ("neighborhood_living", "gymnasium")
    }
    fingerprints = {
        profile_id: sorted({(tuple(row["verbs"]), row["family"], row["volume_count"]) for row in group}, key=str)
        for profile_id, group in profile_groups.items()
    }
    failures: list[str] = []
    for profile_id, group in profile_groups.items():
        if len(group) < 2:
            failures.append(f"{profile_id}_seed_count_below_2")
        if group and mean(row["program_fit_score"] for row in group) < 0.75:
            failures.append(f"{profile_id}_mean_program_fit_below_0.75")
        if group and min(row["architectural_score"] for row in group) < 0.88:
            failures.append(f"{profile_id}_architectural_floor_below_0.88")
        if not all(row["program_hard_pass"] for row in group):
            failures.append(f"{profile_id}_program_hard_gate_failure")
    if len({json.dumps(value, sort_keys=True) for value in fingerprints.values()}) < len(profile_groups):
        failures.append("program_geometry_fingerprints_not_distinct")
    if sum(int(report.get("evaluated_count") or 0) for report in search_reports.values()) < 200:
        failures.append("program_search_did_not_evaluate_200_candidates")
    if sum(int(report.get("rejected_count") or 0) for report in search_reports.values()) < 1:
        failures.append("program_search_rejected_no_invalid_candidates")
    result = {
        "schema_version": "arr.maas.program_massing_benchmark.v1",
        "status": "pass" if not failures else "fail",
        "case_count": len(rows),
        "profile_count": len(profile_groups),
        "mean_program_fit": round(mean(row["program_fit_score"] for row in rows), 4) if rows else 0.0,
        "profile_mean_scores": {
            key: round(mean(row["program_fit_score"] for row in group), 4) if group else 0.0
            for key, group in profile_groups.items()
        },
        "distinct_profile_fingerprint_count": len({json.dumps(value, sort_keys=True) for value in fingerprints.values()}),
        "search_reports": search_reports,
        "rows": rows,
        "failures": failures,
        "png": str(output_png),
    }
    _render_contact_sheet(features, output_png)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def run_neighborhood_20_language_benchmark(*, output_json: Path, output_png: Path) -> dict[str, Any]:
    """Render one 20-language neighborhood-living archive for human review.

    This is intentionally separate from the small cross-program smoke test.
    Program seeds and the neutral architectural-language archive compete under
    the same geometry-derived program gate; source names never satisfy roles.
    """
    base = box(0, 0, 60, 40)
    seeds_by_name = {
        sequence.name: sequence
        for sequence in (*program_seed_sequences("근린생활시설"), *creative_seed_sequences())
    }
    elites, search_report = search_program_elites(
        base,
        building_type="근린생활시설",
        height=15.0,
        floors=5,
        generations=4,
        offspring_per_seed=10,
        random_seed=417,
        target_count=20,
        seed_sequences=tuple(seeds_by_name.values()),
        # The final visual archive still has strict hard geometry/program gates.
        # This floor admits novel source languages for visual comparison instead
        # of forcing every candidate back to the four hand-authored program seeds.
        minimum_architectural_score=0.76,
        selection_minimum_distance=0.16,
    )
    rows: list[dict[str, Any]] = []
    for elite in elites:
        props = elite.feature["properties"]
        program = props["program_massing_evidence"]
        spatial = props["program_spatial_evidence"]
        signature = props["source_signature"]
        projection = spatial["spatial_role_projection"]
        rows.append({
            "variant_id": props["variant_id"],
            "topology": elite.sequence.name.split("__search_", 1)[0],
            "formal_principle": signature.get("formal_principle"),
            "program_fit_score": program["program_fit_score"],
            "architectural_score": spatial["architectural_score"],
            "volume_count": len(elite.source.volumes),
            "surface_count": int(signature.get("effective_surface_count") or signature.get("surface_count") or 0),
            "raw_surface_count": int(signature.get("surface_count") or 0),
            "grounded": bool(projection["active_ground_mass_present"]),
            "public_spatial_gesture": bool(projection["public_spatial_gesture_present"]),
            "hard_pass": bool(program["hard_pass"]),
        })
    topology_count = len({row["topology"] for row in rows})
    principle_count = len({row["formal_principle"] for row in rows})
    near_duplicate_pair_count = sum(
        1 for index, left in enumerate(elites) for right in elites[:index]
        if _descriptor_distance(left, right) < 0.16
    )
    failures: list[str] = []
    if len(rows) != 20:
        failures.append("neighborhood_archive_did_not_select_20")
    if topology_count < 10:
        failures.append("neighborhood_topology_count_below_10")
    if principle_count < 6:
        failures.append("neighborhood_formal_principle_count_below_6")
    if near_duplicate_pair_count > 2:
        failures.append("neighborhood_near_duplicate_pair_count_above_2")
    if not all(row["hard_pass"] and row["grounded"] for row in rows):
        failures.append("neighborhood_program_or_ground_gate_failure")
    if any(row["volume_count"] > 4 or row["surface_count"] > 28 for row in rows):
        failures.append("neighborhood_clean_mass_gate_failure")
    result = {
        "schema_version": "arr.maas.neighborhood_20_language_benchmark.v1",
        "status": "pass" if not failures else "fail",
        "selected_count": len(rows),
        "topology_count": topology_count,
        "formal_principle_count": principle_count,
        "near_duplicate_pair_count": near_duplicate_pair_count,
        "search_report": search_report,
        "rows": rows,
        "failures": failures,
        "png": str(output_png),
    }
    _render_archive_sheet(
        [elite.feature for elite in elites],
        output_png,
        title="MAAS - neighborhood living: 20 program-conditioned mass languages",
    )
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def _render_contact_sheet(features: list[dict[str, Any]], output: Path) -> None:
    card_w, card_h, columns = 720, 570, 2
    rows = (len(features) + columns - 1) // columns
    canvas = Image.new("RGB", (card_w * columns, 72 + card_h * rows), "#07111f")
    draw = ImageDraw.Draw(canvas)
    try:
        title_font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 26)
        label_font = ImageFont.truetype("C:/Windows/Fonts/malgunbd.ttf", 15)
    except OSError:
        title_font = label_font = ImageFont.load_default()
    draw.text((24, 20), "MAAS program-conditioned mass benchmark", fill="#f8fafc", font=title_font)
    with tempfile.TemporaryDirectory(prefix="maas-program-benchmark-") as temporary:
        for index, feature in enumerate(features):
            raw_preview = Image.open(feature_preview_png(feature, Path(temporary))).convert("RGBA")
            preview = Image.new("RGBA", raw_preview.size, "white")
            preview.alpha_composite(raw_preview)
            preview = preview.convert("RGB")
            x = index % columns * card_w
            y = 72 + index // columns * card_h
            canvas.paste(preview, (x, y))
            props = feature["properties"]
            evidence = props["program_massing_evidence"]
            draw.rectangle((x, y + 520, x + card_w, y + card_h), fill="#101d32")
            label = f"{props['building_type']} · {evidence['profile_id']} · fit {evidence['program_fit_score']:.3f} · {props['variant_id']}"
            draw.text((x + 14, y + 534), label, fill="#f8fafc", font=label_font)
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output)


def run_creative_20_archive_benchmark(*, output_json: Path, output_png: Path) -> dict[str, Any]:
    base = box(0, 0, 60, 40)
    elites, search_report = search_creative_elites(
        base,
        height=18.0,
        floors=6,
        generations=5,
        offspring_per_seed=16,
        random_seed=417,
        target_count=20,
    )
    rows = []
    for elite in elites:
        props = elite.feature["properties"]
        evidence = props["creative_mass_evidence"]
        rows.append({
            "variant_id": props["variant_id"],
            "topology": props["variant_id"].split("__search_", 1)[0],
            "score": elite.score,
            "creative_score": evidence["creative_score"],
            "coherence_score": evidence["coherence_score"],
            "dominant_component_ratio": evidence["dominant_component_ratio"],
            "site_coverage_ratio": evidence["site_coverage_ratio"],
            "volume_count": len(props["mass_volumes"]),
            "surface_count": props["source_signature"]["surface_count"],
            "sculptural_geometry": bool(evidence.get("sculptural_geometry")),
            "non_rectilinear_volume_count": int(evidence.get("non_rectilinear_volume_count") or 0),
            "hard_pass": bool(evidence["hard_pass"]),
        })
    topology_count = len({row["topology"] for row in rows})
    geometric_language_count = int(search_report.get("geometric_language_count") or 0)
    near_duplicate_pair_count = sum(
        1
        for index, left in enumerate(elites)
        for right in elites[:index]
        if _descriptor_distance(left, right) < 0.10
    )
    failures = []
    if len(rows) != 20:
        failures.append("archive_did_not_select_20")
    if topology_count < 12:
        failures.append("formal_operation_graph_count_below_12")
    if geometric_language_count < 14:
        failures.append("geometric_language_count_below_14")
    if rows and min(row["creative_score"] for row in rows) < 0.75:
        failures.append("creative_quality_floor_below_0.75")
    if not all(row["hard_pass"] for row in rows):
        failures.append("creative_archive_contains_clean_mass_gate_failure")
    sculptural_count = sum(1 for row in rows if row["sculptural_geometry"])
    if sculptural_count < 12:
        failures.append("sculptural_geometry_count_below_12_competition_target")
    if near_duplicate_pair_count > 2:
        failures.append("near_duplicate_geometry_pair_count_above_2")
    result = {
        "schema_version": "arr.maas.creative_archive_benchmark.v1",
        "stage": "creative_form_exploration",
        "program_conditioned": False,
        "legal_parking_checked": False,
        "status": "pass" if not failures else "fail",
        "selected_count": len(rows),
        "topology_count": topology_count,
        "geometric_language_count": geometric_language_count,
        "mean_creative_score": round(mean(row["creative_score"] for row in rows), 4) if rows else 0.0,
        "minimum_creative_score": min((row["creative_score"] for row in rows), default=0.0),
        "sculptural_geometry_count": sculptural_count,
        "rectilinear_extrusion_count": len(rows) - sculptural_count,
        "near_duplicate_pair_count": near_duplicate_pair_count,
        "search_report": search_report,
        "rows": rows,
        "failures": failures,
        "png": str(output_png),
    }
    board_features = []
    for index, elite in enumerate(elites):
        feature = deepcopy(elite.feature)
        props = feature["properties"]
        source_name = str(props["variant_id"])
        topology = source_name.split("__search_", 1)[0]
        props["archive_variant_id"] = source_name
        props["variant_id"] = f"maas_{index + 1:02d}"
        props["mass_shape"] = topology.replace("creative_", "")
        props["maas_concept"] = "creative source archive; program/legal projection pending"
        props["typology_family"] = props["source_signature"].get("family")
        props["operator_family"] = props["source_signature"].get("family")
        props["maas_sequence_verbs"] = list(props["source_signature"].get("verb_profile") or [])
        props["far"] = 0.0
        props["bcr"] = round(shape(feature["geometry"]).area / float(base.area) * 100.0, 1)
        props["parking_precheck"] = {
            "required_count": {},
            "layout_candidate": {"status": "source archive; legal/parking not run", "provided_spaces": "-", "required_spaces": "-", "stalls": []},
        }
        board_features.append(feature)
    result.update({
        "pnu": "normalized-creative-archive",
        "building_type": "creative mass exploration",
        "elapsed_ms": 0,
        "boundary": {"type": "Feature", "geometry": mapping(base), "properties": {}},
        "response": {"feature_collection": {"type": "FeatureCollection", "features": board_features}},
    })
    _render_archive_sheet([elite.feature for elite in elites], output_png)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def run_housing_20_archive_benchmark(*, output_json: Path, output_png: Path) -> dict[str, Any]:
    """Backward-compatible entry point; the source archive is now program-neutral."""
    return run_creative_20_archive_benchmark(output_json=output_json, output_png=output_png)


def run_site_adaptation_benchmark(*, output_json: Path, output_png: Path) -> dict[str, Any]:
    """Verify that the same languages respond to parcel axes and boundaries."""
    sites = {
        "rotated_long": rotate(box(0, 0, 80, 28), 29, origin="centroid"),
        "trapezoid": Polygon([(0, 0), (72, 7), (61, 45), (8, 38)]),
        "concave_l": Polygon([(0, 0), (68, 0), (68, 24), (31, 24), (31, 52), (0, 52)]),
    }
    wanted = {
        "creative_composed_folded_field_1",
        "creative_graph_bend_ribbon_court",
        "creative_graph_overlap_shift_terrace",
        "creative_graph_clean_courtyard_block",
    }
    sequences = [sequence for sequence in creative_seed_sequences() if sequence.name in wanted]
    rows: list[dict[str, Any]] = []
    features: list[dict[str, Any]] = []
    contexts: dict[str, Any] = {}
    for site_name, site in sites.items():
        contexts[site_name] = build_site_context(
            site_area_m2=float(site.area),
            building_type="creative mass exploration",
            limits={},
            max_variants=len(sequences),
            site_polygon=site,
        )["site_geometry_intelligence"]
        for sequence in sequences:
            source = compile_sequence_to_source_mass(site, sequence)
            if source is None:
                rows.append({"site": site_name, "sequence": sequence.name, "compiled": False})
                continue
            feature = _feature(
                source,
                sequence,
                building_type=f"site-adaptation:{site_name}",
                height=18.0,
                floors=6,
                site_area=float(site.area),
            )
            feature["properties"]["archive_variant_id"] = f"{site_name}__{sequence.name}"
            evidence = attach_creative_mass_evidence(feature, site_area_m2=float(site.area))
            volumes = [shape(item["geometry"]) for item in feature["properties"]["mass_volumes"]]
            within = all(site.buffer(1e-7).covers(volume) for volume in volumes)
            frame = source.signature().get("site_frame_evidence") or {}
            rows.append({
                "site": site_name,
                "sequence": sequence.name,
                "compiled": True,
                "within_site": within,
                "hard_pass": bool(evidence["hard_pass"]),
                "site_frame_angle": frame.get("dominant_axis_world_degrees"),
                "coverage": evidence["site_coverage_ratio"],
                "formal_principle": source.signature().get("formal_principle"),
            })
            features.append(feature)
    failures: list[str] = []
    if len(rows) != len(sites) * len(sequences):
        failures.append("site_language_matrix_incomplete")
    if not all(row.get("compiled") for row in rows):
        failures.append("site_language_compile_failure")
    if not all(row.get("within_site") for row in rows if row.get("compiled")):
        failures.append("source_volume_outside_site")
    if not all(context.get("status") == "available" for context in contexts.values()):
        failures.append("site_geometry_intelligence_missing")
    angles = {round(float(row.get("site_frame_angle") or 0.0), 1) for row in rows if row.get("compiled")}
    if len(angles) < len(sites):
        failures.append("site_axes_not_distinguished")
    result = {
        "schema_version": "arr.maas.site_adaptation_benchmark.v1",
        "status": "pass" if not failures else "fail",
        "site_count": len(sites),
        "language_count": len(sequences),
        "case_count": len(rows),
        "site_geometry_intelligence": contexts,
        "rows": rows,
        "failures": failures,
        "png": str(output_png),
    }
    _render_archive_sheet(
        features,
        output_png,
        title="MAAS - site adaptation: 3 parcels x 4 architectural languages",
    )
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def _archive_review_display(props: dict[str, Any]) -> dict[str, str]:
    review_status = str(props.get("review_status") or "").strip().lower()
    selected = str(
        props.get("portfolio_selection_status") or ""
    ).strip().lower() == "selected"
    reasons = [str(value) for value in props.get("review_reasons") or []]
    if selected:
        status_label = "SELECTED/WARN" if review_status == "warn" else "SELECTED"
        footer_fill = "#4a3514" if review_status == "warn" else "#123524"
        text_fill = "#fcd34d" if review_status == "warn" else "#86efac"
    elif review_status == "accept":
        status_label, footer_fill, text_fill = "ACCEPT", "#123524", "#86efac"
    elif review_status == "warn":
        status_label, footer_fill, text_fill = "WARN", "#4a3514", "#fcd34d"
    elif review_status == "reject":
        status_label, footer_fill, text_fill = "REJECT", "#441d25", "#fda4af"
    else:
        status_label, footer_fill, text_fill = "", "#101d32", "#cbd5e1"
    note = (
        f"{status_label} · {', '.join(reasons[:2]) or 'visual floor pass'}"
        if status_label
        else ""
    )
    return {
        "status_label": status_label,
        "footer_fill": footer_fill,
        "text_fill": text_fill,
        "note": note,
    }


def _render_archive_sheet(
    features: list[dict[str, Any]],
    output: Path,
    *,
    title: str = "MAAS - 20 program-neutral creative mass elites",
) -> None:
    # Human review uses one large isometric image per candidate in the same 5x4
    # arrangement as the established legal board. The VLM still receives the
    # full four-view preview; front/top/opposite are diagnostic evidence and
    # must not visually multiply candidates on the primary review sheet.
    card_w, card_h, columns = 384, 322, 5
    row_count = (len(features) + columns - 1) // columns
    canvas = Image.new("RGB", (card_w * columns, 72 + card_h * row_count), "#07111f")
    draw = ImageDraw.Draw(canvas)
    try:
        title_font = ImageFont.truetype("C:/Windows/Fonts/malgunbd.ttf", 25)
        label_font = ImageFont.truetype("C:/Windows/Fonts/malgunbd.ttf", 13)
        note_font = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", 11)
    except OSError:
        title_font = label_font = note_font = ImageFont.load_default()
    draw.text((24, 20), "MAAS — 20 program-neutral creative mass elites", fill="#f8fafc", font=title_font)
    draw.rectangle((0, 0, canvas.width, 72), fill="#07111f")
    draw.text((24, 20), title, fill="#f8fafc", font=title_font)
    with tempfile.TemporaryDirectory(prefix="maas-creative-archive-") as temporary:
        for index, feature in enumerate(features):
            raw = Image.open(feature_preview_png(feature, Path(temporary))).convert("RGBA")
            raw = raw.crop((0, 0, 360, 250))
            flattened = Image.new("RGBA", raw.size, "white")
            flattened.alpha_composite(raw)
            preview = flattened.convert("RGB").resize((card_w, 260), Image.Resampling.LANCZOS)
            x, y = index % columns * card_w, 72 + index // columns * card_h
            canvas.paste(preview, (x, y))
            props = feature["properties"]
            creative_evidence = props.get("creative_mass_evidence") if isinstance(props.get("creative_mass_evidence"), dict) else {}
            program_evidence = props.get("program_massing_evidence") if isinstance(props.get("program_massing_evidence"), dict) else {}
            display_score = float(creative_evidence.get("creative_score") or program_evidence.get("program_fit_score") or 0.0)
            display_mode = "creative" if creative_evidence else ("program" if program_evidence else "unscored")
            evidence = {"creative_score": display_score}
            review_display = _archive_review_display(props)
            footer_fill = review_display["footer_fill"]
            draw.rectangle((x, y + 260, x + card_w, y + card_h), fill=footer_fill)
            source_id = str(props.get("archive_variant_id") or props["variant_id"])
            topology = str(props.get("mass_shape") or source_id.split("__search_", 1)[0].replace("creative_", ""))
            label = f"{index + 1:02d} {topology} · creative {evidence['creative_score']:.3f}"
            label = f"{index + 1:02d} {topology} - {display_mode} {display_score:.3f}"
            capacity = props.get("capacity_alternative_projection")
            measurement = props.get("source_capacity_measurement")
            if isinstance(capacity, dict) and capacity.get("alternative_id"):
                capacity_labels = {
                    "spatial_reserve": "RESERVE",
                    "balanced_yield": "BALANCED",
                    "brief_target": "BRIEF",
                    "maximum_feasible": "MAX",
                }
                alternative_id = str(capacity["alternative_id"])
                target = float(capacity.get("target_utilization") or 0.0)
                achieved = float((measurement or {}).get("feasible_capacity_utilization") or 0.0)
                far_pct = float((measurement or {}).get("far_pct") or 0.0)
                feasible_floor_area = float(
                    capacity.get("feasible_maximum_floor_area_m2") or 0.0
                )
                base_contract = props.get("base_capacity_contract") or {}
                parcel_area = float(base_contract.get("parcel_area_m2") or 0.0)
                feasible_far = (
                    feasible_floor_area / parcel_area * 100.0
                    if feasible_floor_area > 0.0 and parcel_area > 0.0
                    else 0.0
                )
                label = (
                    f"{index + 1:02d} {topology} - "
                    f"{capacity_labels.get(alternative_id, alternative_id)} "
                    f"{target:.0%}>{achieved:.0%} | FAR {far_pct:.0f}/{feasible_far:.0f}%"
                )
            draw.text((x + 12, y + 274), label, fill="#f8fafc", font=label_font)
            if review_display["status_label"]:
                note = review_display["note"]
                if len(note) > 63:
                    note = note[:60] + "..."
                draw.text(
                    (x + 12, y + 298),
                    note,
                    fill=review_display["text_fill"],
                    font=note_font,
                )
        for index in range(len(features), row_count * columns):
            x, y = index % columns * card_w, 72 + index // columns * card_h
            draw.rectangle((x, y, x + card_w, y + 260), fill="#e8edf2")
            draw.text((x + 24, y + 112), "NO DISTINCT HARD-PASS CANDIDATE", fill="#64748b", font=label_font)
            draw.rectangle((x, y + 260, x + card_w, y + card_h), fill="#441d25")
            draw.text((x + 12, y + 286), "REJECT · silhouette/program/clean gate", fill="#fda4af", font=note_font)
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output)


render_archive_sheet = _render_archive_sheet


__all__ = ["render_archive_sheet", "run_creative_20_archive_benchmark", "run_housing_20_archive_benchmark", "run_neighborhood_20_language_benchmark", "run_program_massing_benchmark", "run_site_adaptation_benchmark"]
