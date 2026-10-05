"""Data-driven program component assemblies for architectural mass seeds."""

from __future__ import annotations

from backend.app.modules.design.generation import paths as _design_paths

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from shapely.affinity import rotate
from shapely.geometry import LineString, Polygon, box
from shapely.ops import nearest_points


ASSEMBLY_PATH = _design_paths.package_root('design/maas/program_massing') / "data" / "component_assemblies.v1.json"


@lru_cache(maxsize=1)
def load_component_assemblies() -> dict[str, Any]:
    payload = json.loads(ASSEMBLY_PATH.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "arr.maas.program_component_assemblies.v1":
        raise ValueError("unsupported component assembly schema")
    return payload


def program_component_specs(
    sequence_name: str,
    legal_footprint: Polygon,
    params: dict[str, Any] | None = None,
    section_graph: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], ...]:
    templates = load_component_assemblies().get("templates") or {}
    template_key = _template_key(templates, sequence_name)
    template = templates.get(template_key)
    if not isinstance(template, dict):
        return ()
    params = params or {}
    section_nodes = tuple(
        dict(node)
        for node in ((section_graph or {}).get("nodes") or ())
        if isinstance(node, dict)
    )
    nodes_by_component: dict[str, list[dict[str, Any]]] = {}
    for node in section_nodes:
        nodes_by_component.setdefault(str(node.get("component_role") or ""), []).append(node)
    minx, miny, maxx, maxy = legal_footprint.bounds
    width, depth = maxx - minx, maxy - miny
    if width <= 0 or depth <= 0:
        return ()
    specs: list[dict[str, Any]] = []
    for index, component in enumerate(template.get("components") or []):
        component_role = str(component["role"])
        role = component_role
        component_nodes = nodes_by_component.get(component_role, [])
        graph_params: dict[str, Any] = {}
        for node in component_nodes:
            if isinstance(node.get("params"), dict):
                graph_params.update(node["params"])
        height = list(component["height"])
        for axis in range(2):
            key = f"component_{index}_height_{axis}"
            height[axis] = _bounded(params.get(key, height[axis]), 0.0, 1.0)
        rotation = _bounded(params.get(f"component_{index}_rotation", component.get("rotation_deg", 0.0)), -35.0, 35.0)
        if height[1] <= height[0] + 0.05:
            continue
        if component.get("path"):
            points = []
            for vertex_index, point in enumerate(component["path"]):
                x = _bounded(params.get(f"component_{index}_vertex_{vertex_index}_x", point[0]), 0.0, 1.0)
                y = _bounded(params.get(f"component_{index}_vertex_{vertex_index}_y", point[1]), 0.0, 1.0)
                points.append((minx + width * x, miny + depth * y))
            width_ratio = _bounded(params.get(f"component_{index}_width_ratio", component.get("width_ratio", 0.08)), 0.025, 0.22)
            path_width_m = min(width, depth) * width_ratio
            raw_geometry = LineString(points).buffer(path_width_m, cap_style=2, join_style=1)
        elif component.get("polygon"):
            points = []
            for vertex_index, point in enumerate(component["polygon"]):
                x = _bounded(params.get(f"component_{index}_vertex_{vertex_index}_x", point[0]), 0.0, 1.0)
                y = _bounded(params.get(f"component_{index}_vertex_{vertex_index}_y", point[1]), 0.0, 1.0)
                points.append((minx + width * x, miny + depth * y))
            raw_geometry = Polygon(points)
        else:
            normalized = list(component["bounds"])
            for axis in range(4):
                key = f"component_{index}_bound_{axis}"
                normalized[axis] = _bounded(params.get(key, normalized[axis]), 0.0, 1.0)
            x0, y0, x1, y1 = normalized
            center_x, center_y = (x0 + x1) / 2.0, (y0 + y1) / 2.0
            half_width = (x1 - x0) * _bounded(graph_params.get("width_scale", 1.0), 0.72, 1.28) / 2.0
            half_depth = (y1 - y0) * _bounded(graph_params.get("depth_scale", 1.0), 0.72, 1.28) / 2.0
            center_x += _bounded(graph_params.get("shift_ratio", 0.0), -0.18, 0.18)
            x0, x1 = max(0.0, center_x - half_width), min(1.0, center_x + half_width)
            y0, y1 = max(0.0, center_y - half_depth), min(1.0, center_y + half_depth)
            if x1 <= x0 + 0.03 or y1 <= y0 + 0.03:
                continue
            raw_geometry = box(minx + width * x0, miny + depth * y0, minx + width * x1, miny + depth * y1)
        if not raw_geometry.is_valid:
            raw_geometry = raw_geometry.buffer(0)
        if raw_geometry.is_empty:
            continue
        geometry = rotate(raw_geometry, rotation, origin="centroid").intersection(legal_footprint)
        if geometry.is_empty or geometry.area < max(1.0, legal_footprint.area * 0.025):
            continue
        if geometry.geom_type != "Polygon":
            geometry = max(geometry.geoms, key=lambda item: item.area)
        if sequence_name.startswith("creative_"):
            role = _creative_role(role)
        spec = {
            "role": role,
            "component_role": component_role,
            "footprint": geometry,
            "bottom_fraction": height[0],
            "top_fraction": height[1],
            "verb": str(component["verb"]),
            "section_nodes": tuple(component_nodes),
        }
        if component.get("path"):
            raw_profile = component.get("roof_profile") or []
            if len(raw_profile) == len(points):
                spec["path_points"] = tuple(points)
                spec["path_width_m"] = path_width_m
                spec["roof_profile"] = tuple(_bounded(value, height[0] + 0.05, 1.0) for value in raw_profile)
        specs.append(spec)
    visible_specs = [spec for spec in specs if not any(node.get("relation") == "subtract" for node in spec.get("section_nodes") or ())]
    subtractors = [spec for spec in specs if spec not in visible_specs]
    for subtractor in subtractors:
        subtractor_nodes = subtractor.get("section_nodes") or ()
        parent_ids = {str(node.get("parent_id") or "") for node in subtractor_nodes}
        parent_roles = {
            str(node.get("component_role") or "")
            for node in section_nodes
            if str(node.get("node_id") or "") in parent_ids
        }
        for parent in visible_specs:
            if parent["role"] not in parent_roles:
                continue
            carved = parent["footprint"].difference(subtractor["footprint"])
            if carved.is_empty:
                continue
            if carved.geom_type != "Polygon":
                carved = max(carved.geoms, key=lambda item: item.area)
            if carved.is_valid and carved.area >= max(1.0, legal_footprint.area * 0.025):
                parent["footprint"] = carved
                parent.setdefault("subtractive_relations", []).append({
                    "void_role": subtractor["role"],
                    "parent_role": parent["role"],
                    "relation": "subtract",
                })
    _materialize_typed_attachments(visible_specs, section_nodes, legal_footprint)
    return tuple(visible_specs)


def _materialize_typed_attachments(
    visible_specs: list[dict[str, Any]],
    section_nodes: tuple[dict[str, Any], ...],
    legal_footprint: Polygon,
) -> None:
    """Execute typed ``attach`` edges as load-path-sized plan connections.

    Section graphs used to describe attachment semantically while normalized
    component rectangles could still stop at a point, a hairline, or a small
    kernel gap.  Such geometry is correctly rejected by the clean-mass gate.
    This pass makes the relation executable without encoding parcel
    coordinates or a completed building template: the landing size is bounded
    by the child and legal-host scales, and an already sufficient connection is
    left untouched.
    """

    if len(visible_specs) < 2 or not section_nodes:
        return
    nodes_by_id = {
        str(node.get("node_id") or ""): node
        for node in section_nodes
        if str(node.get("node_id") or "")
    }
    specs_by_component = {
        str(spec.get("component_role") or spec.get("role") or ""): spec
        for spec in visible_specs
    }
    site_scale = max(float(legal_footprint.area), 1e-9) ** 0.5
    for node in section_nodes:
        if str(node.get("relation") or "").lower() != "attach":
            continue
        child_role = str(node.get("component_role") or "")
        parent_node = nodes_by_id.get(str(node.get("parent_id") or ""))
        parent_role = str((parent_node or {}).get("component_role") or "")
        child = specs_by_component.get(child_role)
        parent = specs_by_component.get(parent_role)
        if child is None or parent is None or child is parent:
            continue
        child_geometry = child["footprint"]
        parent_geometry = parent["footprint"]
        before = _plan_contact_strength(child_geometry, parent_geometry)
        if before >= 0.06:
            child.setdefault("typed_attachment_evidence", []).append({
                "relation": "attach",
                "parent_role": parent_role,
                "status": "already_materialized",
                "contact_strength_before": round(before, 4),
                "contact_strength_after": round(before, 4),
            })
            continue

        child_scale = max(float(child_geometry.area), 1e-9) ** 0.5
        gap = float(child_geometry.distance(parent_geometry))
        maximum_bridge = max(0.25, min(child_scale * 0.35, site_scale * 0.06))
        if gap > maximum_bridge:
            child.setdefault("typed_attachment_evidence", []).append({
                "relation": "attach",
                "parent_role": parent_role,
                "status": "rejected_gap_exceeds_bounded_attachment",
                "plan_gap_m": round(gap, 4),
                "maximum_bridge_m": round(maximum_bridge, 4),
                "contact_strength_before": round(before, 4),
            })
            continue

        # Project the child's representative centre onto the parent first.
        # ``nearest_points(child, parent)`` is ambiguous for parallel edges
        # and GEOS commonly returns an end corner, leaving only one quarter of
        # the landing inside the parent.  The centre projection yields the
        # intended wall/landing relation while remaining coordinate-free.
        parent_point = nearest_points(child_geometry.centroid, parent_geometry)[1]
        child_point = nearest_points(child_geometry, parent_point)[0]
        materialized = None
        after = before
        used_radius = 0.0
        maximum_radius = max(0.12, site_scale * 0.08)
        for radius_ratio in (0.10, 0.14, 0.18, 0.24, 0.30):
            radius = max(0.08, min(child_scale * radius_ratio, maximum_radius))
            landing = box(
                parent_point.x - radius,
                parent_point.y - radius,
                parent_point.x + radius,
                parent_point.y + radius,
            )
            connector = landing
            if gap > 1e-7:
                connector = connector.union(
                    LineString((child_point.coords[0], parent_point.coords[0])).buffer(
                        max(0.06, radius * 0.35),
                        cap_style=2,
                        join_style=2,
                    )
                )
            candidate = child_geometry.union(connector).intersection(legal_footprint)
            if not candidate.is_valid:
                candidate = candidate.buffer(0)
            if candidate.is_empty:
                continue
            if candidate.geom_type != "Polygon":
                candidate = max(
                    (part for part in candidate.geoms if part.geom_type == "Polygon"),
                    key=lambda part: part.area,
                    default=None,
                )
            if candidate is None or candidate.is_empty:
                continue
            candidate_strength = _plan_contact_strength(candidate, parent_geometry)
            if candidate_strength > after:
                materialized = candidate
                after = candidate_strength
                used_radius = radius
            if candidate_strength >= 0.075:
                break
        if materialized is None or after < 0.06:
            child.setdefault("typed_attachment_evidence", []).append({
                "relation": "attach",
                "parent_role": parent_role,
                "status": "unable_to_materialize_bounded_attachment",
                "plan_gap_m": round(gap, 4),
                "contact_strength_before": round(before, 4),
                "contact_strength_after": round(after, 4),
            })
            continue
        child["footprint"] = materialized
        child.setdefault("typed_attachment_evidence", []).append({
            "relation": "attach",
            "parent_role": parent_role,
            "status": "materialized",
            "plan_gap_m": round(gap, 4),
            "landing_radius_m": round(used_radius, 4),
            "contact_strength_before": round(before, 4),
            "contact_strength_after": round(after, 4),
        })


def _plan_contact_strength(left: Polygon, right: Polygon) -> float:
    minimum_area = max(min(float(left.area), float(right.area)), 1e-9)
    intersection_ratio = float(left.intersection(right).area) / minimum_area
    shared_length = float(left.boundary.intersection(right.boundary).length)
    return max(intersection_ratio, shared_length / (minimum_area ** 0.5))


def component_mutation_limits(sequence_name: str) -> dict[str, float]:
    templates = load_component_assemblies().get("templates") or {}
    key = _template_key(templates, sequence_name)
    template = templates.get(key) or {}
    return {key: float(value) for key, value in (template.get("mutation") or {}).items()}


def program_component_family(sequence_name: str) -> str:
    templates = load_component_assemblies().get("templates") or {}
    key = _template_key(templates, sequence_name)
    return str((templates.get(key) or {}).get("family") or "")


def program_component_chassis(sequence_name: str) -> str:
    """Return the normalized plan chassis, independent of roof language."""
    templates = load_component_assemblies().get("templates") or {}
    key = _template_key(templates, sequence_name)
    template = templates.get(key) or {}
    return str(template.get("chassis") or template.get("family") or "")


def _template_key(templates: dict[str, Any], sequence_name: str) -> str:
    candidates = [sequence_name]
    if sequence_name.startswith("creative_"):
        candidates.append(sequence_name.replace("creative_", "program_housing_", 1))
    for candidate in candidates:
        match = next((key for key in templates if candidate == key or candidate.startswith(f"{key}__")), "")
        if match:
            return match
    return ""


def _creative_role(role: str) -> str:
    neutral = role.removeprefix("housing_")
    replacements = {
        "living": "primary",
        "community": "public",
        "shared_entry": "shared_anchor",
        "vertical_entry": "vertical_anchor",
    }
    for source, target in replacements.items():
        neutral = neutral.replace(source, target)
    return f"creative_{neutral}"


def _bounded(value: Any, low: float, high: float) -> float:
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return low


__all__ = ["ASSEMBLY_PATH", "component_mutation_limits", "load_component_assemblies", "program_component_chassis", "program_component_family", "program_component_specs"]
