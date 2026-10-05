"""Bounded generate-evaluate-select loop for program component assemblies."""

from __future__ import annotations

import random
from dataclasses import dataclass, replace
from typing import Any, Literal

from shapely.geometry import Polygon, mapping
from backend.app.modules.design.generation.maas.grammar.verb_sequence import VerbCall, VerbSequence
from backend.app.modules.design.generation.maas.grammar.component_graph import graph_from_sequence, primary_operation_from_sequence
from backend.app.modules.design.generation.maas.source_geometry import compile_sequence_to_source_mass
from backend.app.modules.design.generation.maas.source_geometry.ir import SourceMass

from backend.app.modules.design.generation.maas.program_massing.assembly import component_mutation_limits, load_component_assemblies
from backend.app.modules.design.generation.maas.program_massing.creative import attach_creative_mass_evidence, creative_seed_sequences
from backend.app.modules.design.generation.maas.program_massing.geometry_safety import safe_unary_union
from backend.app.modules.design.generation.maas.program_massing.morphology import intrinsic_shape_distance
from backend.app.modules.design.generation.maas.program_massing.scoring import attach_program_massing_evidence
from backend.app.modules.design.generation.maas.program_massing.sequences import program_seed_sequences


@dataclass(frozen=True)
class ProgramElite:
    sequence: VerbSequence
    source: SourceMass
    feature: dict[str, Any]
    score: float
    generation: int


def search_program_elites(
    base: Polygon,
    *,
    building_type: str,
    height: float,
    floors: int,
    generations: int = 4,
    offspring_per_seed: int = 12,
    random_seed: int = 417,
    target_count: int | None = None,
    seed_sequences: tuple[VerbSequence, ...] | None = None,
    minimum_architectural_score: float = 0.88,
    selection_minimum_distance: float = 0.0,
    accepted_sink: list[ProgramElite] | None = None,
) -> tuple[tuple[ProgramElite, ...], dict[str, Any]]:
    rng = random.Random(random_seed)
    elites: list[ProgramElite] = []
    archive_pool: list[ProgramElite] = []
    evaluated = rejected = 0
    seeds = seed_sequences if seed_sequences is not None else program_seed_sequences(building_type)
    for seed in seeds:
        parent_overrides: dict[str, float] = {}
        best: ProgramElite | None = None
        for generation in range(max(1, generations)):
            candidates = [parent_overrides]
            candidates.extend(_mutated_overrides(seed, parent_overrides, rng) for _ in range(max(1, offspring_per_seed)))
            generation_elites: list[ProgramElite] = []
            for index, overrides in enumerate(candidates):
                candidate = _with_overrides(seed, overrides, generation, index)
                source = compile_sequence_to_source_mass(base, candidate)
                evaluated += 1
                if source is None:
                    rejected += 1
                    continue
                source_signature = source.signature()
                # Program proposals are review masses, not free-form surface
                # studies. A high semantic/program score must not rescue the
                # tangled ribbon failure visible in the PNG contact sheet.
                raw_surfaces = int(source_signature.get("surface_count") or 0)
                effective_surfaces = int(source_signature.get("effective_surface_count") or raw_surfaces)
                # Profiled roofs/ribbons need more raw render faces than a
                # cuboid. Judge normalized complexity separately so the clean
                # gate does not systematically select boxes over continuous
                # geometry. The legal solid count remains hard-limited.
                profiled = bool(source_signature.get("continuous_surface_evidence", {}).get("hard_pass"))
                raw_surface_limit = 160 if profiled else 48
                if len(source.volumes) > 4 or raw_surfaces > raw_surface_limit or effective_surfaces > 28:
                    rejected += 1
                    continue
                feature = _feature(source, candidate, building_type=building_type, height=height, floors=floors, site_area=float(base.area))
                evidence = attach_program_massing_evidence(feature, building_type=building_type)
                spatial = feature["properties"]["program_spatial_evidence"]
                if not evidence["hard_pass"] or float(spatial["architectural_score"]) < minimum_architectural_score:
                    rejected += 1
                    continue
                score = float(evidence["program_fit_score"]) * 0.55 + float(spatial["architectural_score"]) * 0.45
                generation_elites.append(ProgramElite(candidate, source, feature, round(score, 6), generation))
            if generation_elites:
                if accepted_sink is not None:
                    accepted_sink.extend(generation_elites)
                archive_pool.extend(generation_elites)
                generation_elites.sort(key=lambda item: (item.score, item.source.signature()["coherence_evidence"].get("score", 0.0)), reverse=True)
                best = generation_elites[0]
                parent_overrides = _extract_overrides(best.sequence)
        if best is not None:
            elites.append(best)
    if target_count is not None:
        elites = _select_diverse_archive(
            archive_pool,
            target_count=max(1, target_count),
            minimum_distance=max(0.0, min(1.0, selection_minimum_distance)),
            minimum_score=0.75,
        )
    return tuple(elites), {
        "schema_version": "arr.maas.program_search_report.v1",
        "generations": max(1, generations),
        "offspring_per_seed": max(1, offspring_per_seed),
        "evaluated_count": evaluated,
        "rejected_count": rejected,
        "elite_count": len(elites),
        "archive_pool_count": len(archive_pool),
        "target_count": target_count,
        "random_seed": random_seed,
        "seed_count": len(seeds),
        "minimum_architectural_score": minimum_architectural_score,
        "selection_minimum_distance": selection_minimum_distance,
    }


def search_creative_elites(
    base: Polygon,
    *,
    height: float = 18.0,
    floors: int = 6,
    generations: int = 5,
    offspring_per_seed: int = 16,
    random_seed: int = 417,
    target_count: int = 20,
) -> tuple[tuple[ProgramElite, ...], dict[str, Any]]:
    """Search a program-neutral form archive before law and parking projection."""
    rng = random.Random(random_seed)
    archive_pool: list[ProgramElite] = []
    evaluated = rejected = 0
    for seed in creative_seed_sequences():
        parent_overrides: dict[str, float] = {}
        for generation in range(max(1, generations)):
            candidates = [parent_overrides]
            candidates.extend(_mutated_overrides(seed, parent_overrides, rng) for _ in range(max(1, offspring_per_seed)))
            generation_elites: list[ProgramElite] = []
            for index, overrides in enumerate(candidates):
                candidate = _with_overrides(seed, overrides, generation, index, stage="creative")
                source = compile_sequence_to_source_mass(base, candidate)
                evaluated += 1
                if source is None:
                    rejected += 1
                    continue
                feature = _feature(
                    source,
                    candidate,
                    building_type="creative mass exploration",
                    height=height,
                    floors=floors,
                    site_area=float(base.area),
                )
                evidence = attach_creative_mass_evidence(feature, site_area_m2=float(base.area))
                if not evidence["hard_pass"]:
                    rejected += 1
                    continue
                score = float(evidence["creative_score"])
                generation_elites.append(ProgramElite(candidate, source, feature, round(score, 6), generation))
            if generation_elites:
                archive_pool.extend(generation_elites)
                generation_elites.sort(key=lambda item: item.score, reverse=True)
                parent_overrides = _extract_overrides(generation_elites[0].sequence)
    elites = _select_diverse_archive(
        archive_pool,
        target_count=max(1, target_count),
        minimum_sculptural=min(12, target_count),
        minimum_step_anchors=min(2, target_count),
    )
    geometric_language_count = _geometric_language_count(list(elites))
    return tuple(elites), {
        "schema_version": "arr.maas.creative_search_report.v1",
        "stage": "creative_form_exploration",
        "program_conditioned": False,
        "legal_parking_checked": False,
        "generations": max(1, generations),
        "offspring_per_seed": max(1, offspring_per_seed),
        "evaluated_count": evaluated,
        "rejected_count": rejected,
        "elite_count": len(elites),
        "geometric_language_count": geometric_language_count,
        "archive_pool_count": len(archive_pool),
        "target_count": target_count,
        "random_seed": random_seed,
    }


def _select_diverse_archive(
    pool: list[ProgramElite],
    *,
    target_count: int,
    minimum_score: float = 0.75,
    minimum_sculptural: int = 0,
    minimum_step_anchors: int = 0,
    minimum_distance: float = 0.0,
) -> list[ProgramElite]:
    unique: dict[tuple[Any, ...], ProgramElite] = {}
    for item in pool:
        fingerprint = _geometry_fingerprint(item)
        current = unique.get(fingerprint)
        if current is None or item.score > current.score:
            unique[fingerprint] = item
    candidates = [item for item in unique.values() if item.score >= min(1.0, max(0.0, minimum_score))]
    if len(candidates) < target_count:
        candidates = list(unique.values())
    # Do not pre-fill one item for every topology label. Several historical
    # seeds have different names but compile to almost the same geometry; that
    # policy forced near-duplicates onto the review sheet before novelty was
    # ever considered. Select globally by measured plan/section distance and
    # merely cap repetition of any one source graph.
    def _select_with_caps(
        candidates: list[ProgramElite],
        *,
        topology_cap: int,
        principle_cap: int,
        minimum_distance: float,
    ) -> list[ProgramElite]:
        selected: list[ProgramElite] = []
        topology_usage: dict[str, int] = {}
        principle_usage: dict[str, int] = {}
        distance_cache: dict[tuple[int, int], float] = {}

        def distance(left: ProgramElite, right: ProgramElite) -> float:
            key = tuple(sorted((id(left), id(right))))
            if key not in distance_cache:
                distance_cache[key] = _descriptor_distance(left, right)
            return distance_cache[key]

        while candidates and len(selected) < target_count:
            eligible = [
                item for item in candidates
                if topology_usage.get(_topology(item), 0) < topology_cap
                and principle_usage.get(_formal_principle(item), 0) < principle_cap
                and (
                    not selected
                    or min(distance(item, other) for other in selected) >= minimum_distance
                )
            ]
            if not eligible:
                break
            selected_sculptural = sum(1 for item in selected if _is_sculptural(item))
            sculptural_needed = max(0, minimum_sculptural - selected_sculptural)
            selected_step_anchors = sum(1 for item in selected if _is_step_anchor(item))
            step_anchors_needed = max(0, minimum_step_anchors - selected_step_anchors)
            # remaining_slots = target_count - len(selected)
            # Quotas are archive invariants, not late score bonuses. Waiting until
            # ``needed >= remaining_slots`` allowed early rectilinear winners to
            # consume topology/principle capacity and made a 12-form sculptural
            # supply unreachable near the end. Reserve the scarce categories from
            # the start while all geometry-distance and repetition caps still
            # apply.
            if step_anchors_needed > 0:
                step_eligible = [item for item in eligible if _is_step_anchor(item)]
                if sculptural_needed > 0:
                    joint_eligible = [item for item in step_eligible if _is_sculptural(item)]
                    if joint_eligible:
                        step_eligible = joint_eligible
                if step_eligible:
                    eligible = step_eligible
            elif sculptural_needed > 0:
                sculptural_eligible = [item for item in eligible if _is_sculptural(item)]
                if sculptural_eligible:
                    eligible = sculptural_eligible
            def selection_key(item: ProgramElite) -> tuple[float, float]:
                novelty = 1.0 if not selected else min(distance(item, other) for other in selected)
                quota_bonus = 0.08 if sculptural_needed and _is_sculptural(item) else 0.0
                step_bonus = 0.07 if step_anchors_needed and _is_step_anchor(item) else 0.0
                return item.score * 0.46 + novelty * 0.54 + quota_bonus + step_bonus, item.score
            winner = max(eligible, key=selection_key)
            selected.append(winner)
            topology_usage[_topology(winner)] = topology_usage.get(_topology(winner), 0) + 1
            principle = _formal_principle(winner)
            principle_usage[principle] = principle_usage.get(principle, 0) + 1
            candidates.remove(winner)
        return selected

    base_caps = [2, 3, 4]
    base_principle_caps = [4, 6]
    base_distances = [minimum_distance, 0.14, 0.10, 0.06, 0.00]
    for topology_cap in base_caps:
        for principle_cap in base_principle_caps:
            for relaxed_distance in base_distances:
                selected = _select_with_caps(
                    list(candidates),
                    topology_cap=topology_cap,
                    principle_cap=principle_cap,
                    minimum_distance=max(0.0, min(1.0, relaxed_distance)),
                )
                if len(selected) >= target_count:
                    return selected[:target_count]

    # Worst-case fallback: never fail below target_count unless pool itself is
    # too small. Prefer score order so lower-distance gates do not erase the
    # highest-rated architecture entirely.
    return sorted(unique.values(), key=lambda item: item.score, reverse=True)[:target_count]


def _is_sculptural(item: ProgramElite) -> bool:
    evidence = item.feature.get("properties", {}).get("creative_mass_evidence") or {}
    return bool(evidence.get("sculptural_geometry"))


def _formal_principle(item: ProgramElite) -> str:
    return str(item.source.signature().get("formal_principle") or "unclassified")


def _is_step_anchor(item: ProgramElite) -> bool:
    verbs = {call.verb for call in item.sequence.calls}
    principle = _formal_principle(item)
    return "step_envelope" in verbs or "terrace_link" in verbs or principle == "stacked_shifted_platforms"


def _topology(item: ProgramElite) -> str:
    return item.sequence.name.split("__search_", 1)[0]


def _geometry_fingerprint(item: ProgramElite) -> tuple[Any, ...]:
    return tuple(sorted((
        volume.role,
        *(round(value, 1) for value in volume.footprint.bounds),
        round(volume.bottom_fraction, 2),
        round(volume.top_fraction, 2),
    ) for volume in item.source.volumes))


def _descriptor_distance(left: ProgramElite, right: ProgramElite) -> float:
    def vector(item: ProgramElite) -> tuple[float, ...]:
        props = item.feature["properties"]
        evidence = props.get("creative_mass_evidence") or props.get("program_spatial_evidence") or {}
        signature = item.source.signature()
        union = safe_unary_union([volume.footprint for volume in item.source.volumes])
        if union is None or union.is_empty:
            return (0.0,) * 8
        envelope = union.minimum_rotated_rectangle
        envelope_area = max(float(envelope.area), 1e-9)
        compactness = min(1.0, float(union.area) / envelope_area)
        minx, miny, maxx, maxy = union.bounds
        aspect = min(maxx - minx, maxy - miny) / max(max(maxx - minx, maxy - miny), 1e-9)
        height_bands = sorted({round(volume.top_fraction, 2) for volume in item.source.volumes})
        return (
            float(evidence["dominant_component_ratio"]),
            float(evidence["site_coverage_ratio"]),
            min(1.0, float(evidence["height_level_count"]) / 4.0),
            min(1.0, float(signature["surface_count"]) / 48.0),
            compactness,
            aspect,
            min(1.0, len(item.source.volumes) / 5.0),
            sum(height_bands) / max(len(height_bands), 1),
        )
    a, b = vector(left), vector(right)
    # Visual-language novelty is intrinsic to the mass, not to the world-axis
    # direction in which that mass happened to be placed.  Comparing raw site
    # coordinates made a 90-degree rotation or mirror of the same diagram look
    # novel, so the archive could contain one language several times.  Align
    # each source to its own principal frame, normalize scale, and compare all
    # planar dihedral symmetries before adding semantic evidence.
    volume_distance, plan_distance = intrinsic_shape_distance(left.source, right.source)
    scalar_distance = min(1.0, sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5 / 1.35)
    geometric = volume_distance * 0.55 + plan_distance * 0.25 + scalar_distance * 0.20
    left_primary = primary_operation_from_sequence(left.sequence).verb
    right_primary = primary_operation_from_sequence(right.sequence).verb
    left_roles = {str(volume.role).split("_graph_", 1)[0] for volume in left.source.volumes}
    right_roles = {str(volume.role).split("_graph_", 1)[0] for volume in right.source.volumes}
    role_union = left_roles | right_roles
    role_distance = 1.0 - len(left_roles & right_roles) / max(len(role_union), 1)
    semantic = (
        (0.38 if left_primary != right_primary else 0.0)
        + (0.32 if _formal_principle(left) != _formal_principle(right) else 0.0)
        + role_distance * 0.30
    )
    # Labels cannot rescue geometry-equivalent candidates. This is important
    # for LLM-authored graphs, where different prose or node names can compile
    # to the same mass. Site/access response is audited separately on each
    # candidate and must not masquerade as a new formal language.
    if volume_distance * 0.7 + plan_distance * 0.3 <= 0.075:
        return min(0.075, geometric)
    # Geometry remains the majority signal, but genuinely different bend and
    # courtyard graphs should not collapse merely because FAR is similar.
    return min(1.0, geometric * 0.78 + semantic * 0.22)


def _volumetric_distance(left: SourceMass, right: SourceMass) -> float:
    """Normalized 3D symmetric difference for layered planar mass volumes."""
    levels = sorted({
        round(value, 6)
        for source in (left, right)
        for volume in source.volumes
        for value in (volume.bottom_fraction, volume.top_fraction)
    })
    union_volume = difference_volume = 0.0
    for lower, upper in zip(levels, levels[1:]):
        thickness = upper - lower
        if thickness <= 1e-9:
            continue
        middle = (lower + upper) / 2.0
        left_active = [volume.footprint for volume in left.volumes if volume.bottom_fraction <= middle < volume.top_fraction]
        right_active = [volume.footprint for volume in right.volumes if volume.bottom_fraction <= middle < volume.top_fraction]
        left_slice = safe_unary_union(left_active)
        right_slice = safe_unary_union(right_active)
        if left_slice is None and right_slice is None:
            continue
        if left_slice is None:
            slice_union = slice_difference = float(right_slice.area)
        elif right_slice is None:
            slice_union = slice_difference = float(left_slice.area)
        else:
            slice_union = float(left_slice.union(right_slice).area)
            slice_difference = float(left_slice.symmetric_difference(right_slice).area)
        union_volume += slice_union * thickness
        difference_volume += slice_difference * thickness
    return min(1.0, difference_volume / max(union_volume, 1e-9))


def _geometric_language_count(items: list[ProgramElite], *, threshold: float = 0.16) -> int:
    """Count visibly distinct geometry groups, independent of topology labels."""
    representatives: list[ProgramElite] = []
    for item in sorted(items, key=lambda candidate: candidate.score, reverse=True):
        if all(_descriptor_distance(item, other) >= threshold for other in representatives):
            representatives.append(item)
    return len(representatives)


def _mutated_overrides(seed: VerbSequence, parent: dict[str, float], rng: random.Random) -> dict[str, float]:
    payload = load_component_assemblies()
    templates = payload.get("templates") or {}
    template_name = seed.name.replace("creative_", "program_housing_", 1) if seed.name.startswith("creative_") else seed.name
    template = templates.get(template_name)
    if template is None:
        return _mutated_graph_parameters(seed, parent, rng)
    limits = component_mutation_limits(seed.name)
    coord_delta = limits.get("coordinate_delta", 0.03)
    height_delta = limits.get("height_delta", 0.05)
    rotation_delta = limits.get("rotation_delta", 0.0)
    result: dict[str, float] = {}
    for index, component in enumerate(template.get("components") or []):
        if component.get("polygon") or component.get("path"):
            points = component.get("polygon") or component.get("path")
            for vertex_index, point in enumerate(points):
                for axis, baseline in zip(("x", "y"), point):
                    key = f"component_{index}_vertex_{vertex_index}_{axis}"
                    center = parent.get(key, float(baseline))
                    result[key] = round(max(0.0, min(1.0, center + rng.uniform(-coord_delta, coord_delta))), 4)
            if component.get("path"):
                key = f"component_{index}_width_ratio"
                center = parent.get(key, float(component.get("width_ratio", 0.08)))
                result[key] = round(max(0.025, min(0.22, center + rng.uniform(-coord_delta * 0.45, coord_delta * 0.45))), 4)
        else:
            for axis, baseline in enumerate(component["bounds"]):
                key = f"component_{index}_bound_{axis}"
                center = parent.get(key, float(baseline))
                result[key] = round(max(0.0, min(1.0, center + rng.uniform(-coord_delta, coord_delta))), 4)
        for axis, baseline in enumerate(component["height"]):
            key = f"component_{index}_height_{axis}"
            center = parent.get(key, float(baseline))
            result[key] = round(max(0.0, min(1.0, center + rng.uniform(-height_delta, height_delta))), 4)
        if rotation_delta > 0 or component.get("rotation_deg"):
            key = f"component_{index}_rotation"
            center = parent.get(key, float(component.get("rotation_deg", 0.0)))
            result[key] = round(max(-35.0, min(35.0, center + rng.uniform(-rotation_delta, rotation_delta))), 3)
    return result


def _mutated_graph_parameters(seed: VerbSequence, parent: dict[str, float], rng: random.Random) -> dict[str, float]:
    """Mutate parameters on every MassDSL call while preserving its graph topology."""
    result: dict[str, float] = {}
    for call_index, operation in enumerate(seed.calls[1:], start=1):
        for name, baseline_value in operation.params.items():
            if name in {"control_points", "plan_control_points"} and isinstance(baseline_value, list):
                # A section/ribbon control field is part of the genotype, not
                # inert provenance. Earlier search only perturbed scalar
                # ratios, so one good authored loft produced many renamed but
                # geometrically identical descendants. Mutate the normalized
                # stations and heights directly while preserving their order.
                is_plan_polygon = name == "plan_control_points"
                prefix = "plan_control_point" if is_plan_polygon else "control_point"
                limit = 8 if is_plan_polygon else 6
                controls: list[tuple[float, float]] = []
                for point_index, point in enumerate(baseline_value[:limit]):
                    if not isinstance(point, (list, tuple)) or len(point) != 2:
                        continue
                    try:
                        baseline_u, baseline_v = float(point[0]), float(point[1])
                    except (TypeError, ValueError):
                        continue
                    u_key = f"call_{call_index}__{prefix}_{point_index}_u"
                    v_key = f"call_{call_index}__{prefix}_{point_index}_v"
                    center_u = parent.get(u_key, baseline_u)
                    center_v = parent.get(v_key, baseline_v)
                    visible_direction = -1.0 if rng.random() < 0.5 else 1.0
                    controls.append((
                        max(0.03, min(0.97, center_u + rng.uniform(-0.075 if is_plan_polygon else -0.04, 0.075 if is_plan_polygon else 0.04))),
                        # Make section mutations visible at contact-sheet
                        # scale. Tiny +/-0.03 edits survived numerically but
                        # were correctly rejected as the same silhouette.
                        max(
                            0.03 if is_plan_polygon else 0.12,
                            min(
                                0.97 if is_plan_polygon else 0.88,
                                center_v + visible_direction * rng.uniform(0.055, 0.11) if is_plan_polygon
                                else center_v + visible_direction * rng.uniform(0.10, 0.22),
                            ),
                        ),
                    ))
                if is_plan_polygon:
                    candidate = Polygon(controls)
                    if not candidate.is_valid or candidate.area < 0.04:
                        controls = [tuple(map(float, point)) for point in baseline_value[:limit]]
                else:
                    controls.sort(key=lambda item: item[0])
                for point_index, (position, height) in enumerate(controls):
                    # Keep a real section domain and avoid self-crossing or
                    # near-zero spans after mutation.
                    if not is_plan_polygon:
                        low = 0.03 if point_index == 0 else controls[point_index - 1][0] + 0.035
                        remaining = len(controls) - point_index - 1
                        high = 0.97 - remaining * 0.035
                        position = max(low, min(high, position))
                        controls[point_index] = (position, height)
                    result[f"call_{call_index}__{prefix}_{point_index}_u"] = round(position, 4)
                    result[f"call_{call_index}__{prefix}_{point_index}_v"] = round(height, 4)
                continue
            if name == "top_height_controls" and isinstance(baseline_value, list):
                for point_index, baseline_height in enumerate(baseline_value[:8]):
                    try:
                        baseline_height = float(baseline_height)
                    except (TypeError, ValueError):
                        continue
                    key = f"call_{call_index}__top_height_control_{point_index}"
                    center = parent.get(key, baseline_height)
                    result[key] = round(max(0.42, min(1.0, center + rng.uniform(-0.12, 0.12))), 4)
                continue
            if isinstance(baseline_value, bool) or not isinstance(baseline_value, (int, float)):
                continue
            key = f"call_{call_index}__{name}"
            center = parent.get(key, float(baseline_value))
            if name == "angle":
                value = max(-70.0, min(70.0, center + rng.uniform(-9.0, 9.0)))
            elif name == "n":
                value = float(max(2, min(5, round(center + rng.choice((-1, 0, 1))))))
            elif name in {"shift", "distance_ratio"}:
                value = max(-0.30, min(0.30, center + rng.uniform(-0.055, 0.055)))
            elif name == "gap":
                value = max(0.015, min(0.14, center + rng.uniform(-0.018, 0.018)))
            elif "ratio" in name or name in {"factor", "inner_scale", "guest_scale", "length", "size"}:
                value = max(0.10, min(0.96, center + rng.uniform(-0.075, 0.075)))
            else:
                value = center + rng.uniform(-0.06, 0.06)
            result[key] = round(value, 4)
    return result


def _with_overrides(seed: VerbSequence, overrides: dict[str, float], generation: int, index: int, *, stage: str = "program") -> VerbSequence:
    calls = list(seed.calls)
    component_overrides = {key: value for key, value in overrides.items() if key.startswith("component_")}
    if component_overrides:
        last = calls[-1]
        calls[-1] = VerbCall(last.verb, {**last.params, **component_overrides})
    for call_index, operation in enumerate(calls):
        prefix = f"call_{call_index}__"
        changes = {key[len(prefix):]: value for key, value in overrides.items() if key.startswith(prefix)}
        if changes:
            params = dict(operation.params)
            control_changes = {
                key: value for key, value in changes.items()
                if key.startswith("control_point_")
            }
            plan_control_changes = {
                key: value for key, value in changes.items()
                if key.startswith("plan_control_point_")
            }
            height_control_changes = {
                key: value for key, value in changes.items()
                if key.startswith("top_height_control_")
            }
            for key, value in changes.items():
                if key not in control_changes and key not in plan_control_changes and key not in height_control_changes:
                    params[key] = value
            if control_changes and isinstance(params.get("control_points"), list):
                controls = [list(point) for point in params["control_points"] if isinstance(point, (list, tuple)) and len(point) == 2]
                for key, value in control_changes.items():
                    parts = key.split("_")
                    if len(parts) != 4 or parts[0:2] != ["control", "point"]:
                        continue
                    try:
                        point_index = int(parts[2])
                    except ValueError:
                        continue
                    if not 0 <= point_index < len(controls):
                        continue
                    coordinate_index = 0 if parts[3] == "u" else 1 if parts[3] == "v" else -1
                    if coordinate_index >= 0:
                        controls[point_index][coordinate_index] = float(value)
                controls.sort(key=lambda point: float(point[0]))
                params["control_points"] = controls
            if plan_control_changes and isinstance(params.get("plan_control_points"), list):
                controls = [list(point) for point in params["plan_control_points"] if isinstance(point, (list, tuple)) and len(point) == 2]
                for key, value in plan_control_changes.items():
                    parts = key.split("_")
                    if len(parts) != 5 or parts[0:3] != ["plan", "control", "point"]:
                        continue
                    try:
                        point_index = int(parts[3])
                    except ValueError:
                        continue
                    coordinate_index = 0 if parts[4] == "u" else 1 if parts[4] == "v" else -1
                    if 0 <= point_index < len(controls) and coordinate_index >= 0:
                        controls[point_index][coordinate_index] = float(value)
                candidate = Polygon(controls)
                if candidate.is_valid and candidate.area >= 0.04:
                    params["plan_control_points"] = controls
            if height_control_changes and isinstance(params.get("top_height_controls"), list):
                heights = [float(value) for value in params["top_height_controls"]]
                for key, value in height_control_changes.items():
                    parts = key.split("_")
                    if len(parts) != 4 or parts[0:3] != ["top", "height", "control"]:
                        continue
                    try:
                        point_index = int(parts[3])
                    except ValueError:
                        continue
                    if 0 <= point_index < len(heights):
                        heights[point_index] = float(value)
                params["top_height_controls"] = heights
            calls[call_index] = VerbCall(operation.verb, params)
    # Graph-native sequences carry the executable genotype in the
    # ``component_graph_json`` note. Rebuilding only the flat calls leaves that
    # envelope unchanged, so the compiler reads the parent graph and thousands
    # of apparent search mutations become geometry-identical no-ops. Update
    # node operations and reserialize one canonical graph envelope.
    graph = graph_from_sequence(seed)
    if len(graph.nodes) != len(calls):
        # This should be impossible for a valid V2 envelope, but returning an
        # explicitly invalid-free flat sequence is safer than indexing the
        # wrong node. Compiler validation remains the final boundary.
        return VerbSequence(
            name=f"{seed.name}__search_g{generation}_{index}",
            label=seed.label,
            calls=tuple(calls),
            notes=graph.notes + (f"{stage}_component_search=bounded_generate_evaluate_select",),
        )
    name = f"{seed.name}__search_g{generation}_{index}"
    revised_graph = replace(
        graph,
        name=name,
        nodes=tuple(
            replace(node, operation=operation)
            for node, operation in zip(graph.nodes, calls)
        ),
        notes=graph.notes + (f"{stage}_component_search=bounded_generate_evaluate_select",),
    )
    return revised_graph.to_sequence(name=name)


def _extract_overrides(sequence: VerbSequence) -> dict[str, float]:
    result = {key: float(value) for key, value in sequence.calls[-1].params.items() if key.startswith("component_")}
    for call_index, operation in enumerate(sequence.calls):
        for key, value in operation.params.items():
            if key in {"control_points", "plan_control_points"} and isinstance(value, list):
                prefix = "plan_control_point" if key == "plan_control_points" else "control_point"
                limit = 8 if key == "plan_control_points" else 6
                for point_index, point in enumerate(value[:limit]):
                    if not isinstance(point, (list, tuple)) or len(point) != 2:
                        continue
                    try:
                        result[f"call_{call_index}__{prefix}_{point_index}_u"] = float(point[0])
                        result[f"call_{call_index}__{prefix}_{point_index}_v"] = float(point[1])
                    except (TypeError, ValueError):
                        continue
                continue
            if key == "top_height_controls" and isinstance(value, list):
                for point_index, height in enumerate(value[:8]):
                    try:
                        result[f"call_{call_index}__top_height_control_{point_index}"] = float(height)
                    except (TypeError, ValueError):
                        continue
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            result[f"call_{call_index}__{key}"] = float(value)
    return result


def program_seed_variants(
    seed: VerbSequence,
    *,
    count: int = 3,
    random_seed: int = 417,
) -> tuple[VerbSequence, ...]:
    """Return deterministic bounded component-graph parents for one program seed."""
    count = max(1, min(8, int(count)))
    rng = random.Random(random_seed)
    variants = [seed]
    for index in range(1, count):
        overrides = _mutated_overrides(seed, {}, rng)
        variants.append(_with_overrides(seed, overrides, 0, index, stage="program_parent"))
    return tuple(variants)


def _surface_summary(
    source: SourceMass,
    *,
    materialization: str,
) -> dict[str, Any]:
    profiled = tuple(
        surface
        for surface in source.surfaces
        if surface.surface_type.startswith("profiled_")
    )
    return {
        "raw_surface_count": len(source.surfaces),
        "profiled_surface_count": len(profiled),
        "profiled_roof_count": sum(
            "roof" in surface.surface_type for surface in profiled
        ),
        "surface_roles": sorted({surface.role for surface in source.surfaces}),
        "surface_types": sorted({
            surface.surface_type for surface in source.surfaces
        }),
        "materialization": materialization,
    }


def materialize_source_feature_surfaces(
    feature: dict[str, Any],
    source: SourceMass,
    *,
    height: float,
) -> dict[str, Any]:
    """Attach renderer records on demand without changing their eager contract."""

    props = feature.setdefault("properties", {})
    existing_surfaces = props.get("source_surfaces")
    artifact = props.get("geometry_artifact")
    artifact_certificate = (
        artifact.get("projectedVisualCertificate")
        if isinstance(artifact, dict)
        else None
    )
    from backend.app.modules.design.generation.maas.geometry_language.projected_visual_contract import CertifiedMassArtifact, FINAL_AUTHORITY_CERTIFICATION_MODE, FINAL_CERTIFICATE_SCHEMA

    if (
        isinstance(artifact_certificate, dict)
        and artifact_certificate.get("certification_mode")
        == FINAL_AUTHORITY_CERTIFICATION_MODE
        and artifact_certificate.get("schema_version")
        == FINAL_CERTIFICATE_SCHEMA
    ):
        authority_context = props.get("final_semantic_anchor")
        certified = CertifiedMassArtifact.load(
            artifact,
            authority_context=(
                authority_context
                if isinstance(authority_context, dict)
                else {}
            ),
        )
        binding = certified.feature_binding()
        if existing_surfaces != binding["source_surfaces"]:
            raise ValueError(
                "certified MASS artifact source surface binding mismatch"
            )
        if (
            str(props.get("certified_mass_artifact_core_hash") or "")
            != certified.core_hash
        ):
            raise ValueError(
                "certified MASS artifact core hash binding mismatch"
            )
        return feature
    certificate = props.get("floorwise_visual_projection")
    if not isinstance(certificate, dict):
        model = props.get("maas_model")
        certificate = (
            model.get("floorwise_visual_projection")
            if isinstance(model, dict)
            else None
        )
    if (
        isinstance(existing_surfaces, list)
        and existing_surfaces
        and isinstance(certificate, dict)
        and certificate.get("schema_version")
        == "arr.maas.floorwise_visual_projection.v1"
        and certificate.get("status") == "certified"
        and certificate.get("hard_pass") is True
        and bool(str(certificate.get("visual_hash") or ""))
        and int(certificate.get("projected_surface_count") or 0)
        == len(existing_surfaces)
    ):
        return feature

    origin = source.footprint.centroid
    source_surfaces = []
    for surface in source.surfaces:
        record = surface.authority_record()
        record["vertices_world_m"] = [
            [round(float(origin.x) + x, 3), round(float(origin.y) + y, 3), round(height * z, 3)]
            for x, y, z in surface.vertices_m
        ]
        source_surfaces.append(record)
    props["source_surfaces"] = source_surfaces
    props["source_surface_summary"] = _surface_summary(
        source,
        materialization="eager",
    )
    source_certificate = source.metadata.get("floorwise_visual_projection")
    if isinstance(source_certificate, dict):
        # The surfaces above were materialized from this exact current source.
        # Keep their certificate on the same authority instead of retaining a
        # stale summary-only feature certificate from an earlier BOOK stage.
        props["floorwise_visual_projection"] = dict(source_certificate)
        model = props.get("maas_model")
        if isinstance(model, dict):
            model["floorwise_visual_projection"] = dict(source_certificate)
    return feature


def _feature(
    source: SourceMass,
    sequence: VerbSequence,
    *,
    building_type: str,
    height: float,
    floors: int,
    site_area: float,
    surface_materialization: Literal["eager", "summary_only"] = "eager",
) -> dict[str, Any]:
    if surface_materialization not in {"eager", "summary_only"}:
        raise ValueError(
            "surface_materialization must be 'eager' or 'summary_only'"
        )
    feature = {
        "type": "Feature",
        "geometry": mapping(source.footprint),
        "properties": {
            "variant_id": sequence.name,
            "mass_shape": source.name,
            "building_type": building_type,
            "height": height,
            "num_floors": floors,
            "benchmark_site_area_m2": site_area,
            "mass_volumes": [{
                "geometry": mapping(volume.footprint),
                "bottom_height": round(height * volume.bottom_fraction, 3),
                "top_height": round(height * volume.top_fraction, 3),
                "role": volume.role,
            } for volume in source.volumes],
            "source_surface_summary": _surface_summary(
                source,
                materialization=surface_materialization,
            ),
            "source_signature": source.signature(),
            "component_graph": graph_from_sequence(sequence).to_dict(),
            "maas_verb_sequence": sequence.to_list(),
            "maas_model": {},
        },
    }
    if surface_materialization == "eager":
        materialize_source_feature_surfaces(feature, source, height=height)
    return feature


source_feature = _feature


__all__ = [
    "ProgramElite",
    "materialize_source_feature_surfaces",
    "program_seed_variants",
    "search_creative_elites",
    "search_program_elites",
    "source_feature",
]
