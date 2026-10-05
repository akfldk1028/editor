"""Architecture-grade formal-principle source geometry.

This layer translates book/precedent references into architectural massing
principles. It does not decide legality; the legal optimizer still validates,
clips, or rejects every candidate after these source volumes are created.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import pi, sin
from typing import Any

from shapely.affinity import rotate, scale, translate
from shapely.geometry import MultiPolygon, Polygon, box
from shapely.ops import unary_union

from backend.app.modules.design.generation.maas.source_geometry.design_fields import build_ribbon_design_field
from backend.app.modules.design.generation.maas.source_geometry.ir import SourceVolume
from backend.app.modules.design.generation.maas.source_geometry.parametric_curves import swept_ribbon, swept_variable_ribbon
from backend.app.modules.design.generation.maas.source_geometry.section_fields import build_section_loft_field
from backend.app.modules.design.generation.maas.source_geometry.oblique_fields import build_oblique_envelope_field


CANONICAL_FORMAL_PRINCIPLES = {
    "slender_podium_tower",
    "undercut_tapered_tower",
    "torqued_stack",
    "stacked_shifted_platforms",
    "folded_section",
    "terraced_ribbon_section",
    "carved_atrium",
    "split_bridge_connector",
    "carved_monolith",
    "continuous_ribbon_field",
}

FORMAL_PRINCIPLE_ALIASES = {
    "tower_base": "slender_podium_tower",
    "slender_tower": "slender_podium_tower",
    "podium_tower": "slender_podium_tower",
    "undercut_podium": "undercut_tapered_tower",
    "torqued_taper": "undercut_tapered_tower",
    "tapered_tower": "undercut_tapered_tower",
    "twisted_tower": "torqued_stack",
    "torque": "torqued_stack",
    "torqued": "torqued_stack",
    "slab_stack": "stacked_shifted_platforms",
    "platform_stack": "stacked_shifted_platforms",
    "datum_shift": "stacked_shifted_platforms",
    "shifted_platforms": "stacked_shifted_platforms",
    "folded_roof_volume": "folded_section",
    "folded_roof": "folded_section",
    "sloped_roof": "folded_section",
    "terrace_link": "terraced_ribbon_section",
    "terrace_ribbon": "terraced_ribbon_section",
    "terraced_ribbon": "terraced_ribbon_section",
    "continuous_ribbon": "continuous_ribbon_field",
    "ribbon_field": "continuous_ribbon_field",
    "figure_ground": "carved_atrium",
    "carved_solid": "carved_monolith",
    "embedded_void": "carved_monolith",
    "carved_void": "carved_monolith",
    "split_bridge": "split_bridge_connector",
    "bridge_connector": "split_bridge_connector",
}


@dataclass(frozen=True)
class FormalPrincipleResult:
    principle: str
    volumes: tuple[SourceVolume, ...]
    evidence: dict[str, Any]


def normalize_formal_principle(value: str | None) -> str:
    token = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    if token in CANONICAL_FORMAL_PRINCIPLES:
        return token
    return FORMAL_PRINCIPLE_ALIASES.get(token, "")


def _bounds(poly: Polygon) -> tuple[float, float, float, float, float, float]:
    minx, miny, maxx, maxy = poly.bounds
    return minx, miny, maxx, maxy, maxx - minx, maxy - miny


def _clean_piece(role: str, geom, bottom: float, top: float, verb: str, *, clip: Polygon, min_area: float) -> SourceVolume | None:
    clipped = geom.intersection(clip)
    if clipped.is_empty or clipped.area < min_area:
        return None
    if isinstance(clipped, MultiPolygon):
        clipped = max(clipped.geoms, key=lambda item: item.area)
    if not isinstance(clipped, Polygon):
        return None
    bottom = max(0.0, min(0.92, float(bottom)))
    top = max(bottom + 0.07, min(1.0, float(top)))
    return SourceVolume(role, clipped, bottom, top, verb)


def _continuous_field_proxy(geometry, *, clip: Polygon, min_area: float) -> Polygon | None:
    """Build one clean occupancy proxy while retaining the exact surface graph.

    A trunk plus two swept arms can leave tessellation notches and a tiny
    enclosed ring after union. Those details belong to the profiled surface
    specs, not to the legal/FAR proxy. Simplify with a scale-relative bound,
    retain at least 97% of plan area, and always clip back to the host.
    """
    if geometry is None or geometry.is_empty:
        return None
    if isinstance(geometry, MultiPolygon):
        geometry = max(geometry.geoms, key=lambda item: item.area)
    if not isinstance(geometry, Polygon):
        return None
    filled = Polygon(geometry.exterior)
    original_area = float(filled.area)
    tolerance = min(0.75, max(0.05, original_area ** 0.5 * 0.018))
    simplified = filled.simplify(tolerance, preserve_topology=True).intersection(clip)
    if isinstance(simplified, MultiPolygon):
        simplified = max(simplified.geoms, key=lambda item: item.area)
    if not isinstance(simplified, Polygon) or simplified.area < min_area:
        return filled.intersection(clip)
    area_retention = float(simplified.area) / max(original_area, 1e-9)
    if area_retention < 0.97 or area_retention > 1.03:
        return filled.intersection(clip)
    return simplified


def _rect(role: str, clip: Polygon, x0: float, y0: float, x1: float, y1: float, bottom: float, top: float, verb: str, *, min_area: float) -> SourceVolume | None:
    return _clean_piece(role, box(x0, y0, x1, y1), bottom, top, verb, clip=clip, min_area=min_area)


def _rot(role: str, clip: Polygon, geom, angle: float, bottom: float, top: float, verb: str, *, min_area: float) -> SourceVolume | None:
    return _clean_piece(role, rotate(geom, angle, origin=(clip.centroid.x, clip.centroid.y)), bottom, top, verb, clip=clip, min_area=min_area)


def _poly(role: str, clip: Polygon, coords: list[tuple[float, float]], bottom: float, top: float, verb: str, *, min_area: float) -> SourceVolume | None:
    return _clean_piece(role, Polygon(coords), bottom, top, verb, clip=clip, min_area=min_area)


def _ribbon(
    role: str,
    clip: Polygon,
    points: list[tuple[float, float]],
    width: float,
    bottom: float,
    top: float,
    verb: str,
    *,
    min_area: float,
    width_profile: tuple[float, ...] = (),
) -> SourceVolume | None:
    if len(points) < 2 or width <= 0:
        return None
    sweep = (
        swept_variable_ribbon(tuple(points), half_widths=width_profile, clip=clip)
        if len(width_profile) >= 2
        else swept_ribbon(tuple(points), half_width=width, clip=clip)
    )
    if sweep is None:
        return None
    return _clean_piece(role, sweep, bottom, top, verb, clip=clip, min_area=min_area)


def _param(params: dict[str, Any], keys: tuple[str, ...], fallback: float, low: float, high: float) -> float:
    for key in keys:
        try:
            return max(low, min(high, float(params[key])))
        except (KeyError, TypeError, ValueError):
            continue
    return max(low, min(high, float(fallback)))


def _role(role: str, genome: dict[str, Any]) -> str:
    family = str(genome.get("family") or "").strip().lower().replace("-", "_")
    if not family or family in role:
        return role
    if role.startswith("primary_torqued_plate_"):
        return role.replace("primary_torqued_plate_", f"primary_{family}_torqued_plate_", 1)
    if role.startswith("primary_folded_"):
        return role.replace("primary_folded_", f"primary_{family}_folded_", 1)
    if role.startswith("primary_shifted_platform_"):
        return role.replace("primary_shifted_platform_", f"primary_{family}_shifted_platform_", 1)
    if role.startswith("secondary_torque_"):
        return role.replace("secondary_torque_", f"secondary_{family}_torque_", 1)
    if role.startswith("secondary_vertical_datum_"):
        return role.replace("secondary_vertical_datum_", f"secondary_{family}_vertical_datum_", 1)
    if role.startswith("primary_carved_"):
        return role.replace("primary_carved_", f"primary_{family}_carved_", 1)
    if role.startswith("secondary_void_"):
        return role.replace("secondary_void_", f"secondary_{family}_void_", 1)
    if role.startswith("secondary_monolith_"):
        return role.replace("secondary_monolith_", f"secondary_{family}_monolith_", 1)
    if role.startswith("primary_split_"):
        return role.replace("primary_split_", f"primary_{family}_split_", 1)
    if role.startswith("primary_diagonal_bridge_"):
        return role.replace("primary_diagonal_bridge_", f"primary_{family}_diagonal_bridge_", 1)
    if role.startswith("secondary_threshold_"):
        return role.replace("secondary_threshold_", f"secondary_{family}_threshold_", 1)
    return role


def compile_formal_principle_volumes(
    footprint: Polygon,
    *,
    formal_principle: str | None,
    dominant_gesture: str | None,
    language_params: dict[str, Any],
    lower_fraction: float | None,
    last_verb: str,
    massing_genome: dict[str, Any] | None = None,
) -> FormalPrincipleResult | None:
    principle = normalize_formal_principle(formal_principle)
    if not principle or footprint.is_empty:
        return None
    minx, miny, maxx, maxy, width, depth = _bounds(footprint)
    if width <= 0 or depth <= 0:
        return None
    cx, cy = footprint.centroid.x, footprint.centroid.y
    min_area = max(1.0, footprint.area * 0.045)
    split = max(0.22, min(0.70, float(lower_fraction if lower_fraction is not None else 0.42)))
    upper_ratio = _param(language_params, ("upper_ratio", "top_ratio"), 0.84, 0.58, 1.0)
    taper = _param(language_params, ("taper_ratio", "x_ratio", "y_ratio", "top_ratio"), 0.66, 0.42, 0.88)
    shift = _param(language_params, ("distance_ratio", "shift_ratio", "offset_ratio"), 0.16, 0.04, 0.34)
    angle = _param(language_params, ("angle",), 24.0, -42.0, 42.0)
    void_ratio = _param(language_params, ("ratio", "void_ratio", "guest_scale", "inner_scale"), 0.30, 0.16, 0.56)
    pieces: list[SourceVolume | None] = []
    surface_field_specs: list[dict[str, Any]] = []
    section_field_evidence: dict[str, Any] = {}
    oblique_field_evidence: dict[str, Any] = {}
    genome = massing_genome or {}

    if principle == "slender_podium_tower":
        tower_w = width * max(0.20, min(0.42, taper))
        tower_d = depth * max(0.20, min(0.42, taper))
        pieces = [
            _rect("primary_podium_slab", footprint, minx, miny, maxx, maxy, 0.0, split, "base", min_area=min_area),
            _rect("primary_slender_tower", footprint, cx - tower_w / 2, cy - tower_d / 2, cx + tower_w / 2, cy + tower_d / 2, split * 0.82, 1.0, last_verb, min_area=min_area),
            _rect("secondary_ground_carve", footprint, minx, miny, minx + width * 0.28, miny + depth * 0.30, 0.0, max(split * 0.62, 0.18), "void", min_area=min_area),
            _rect("secondary_podium_liner", footprint, minx, maxy - depth * 0.16, maxx, maxy, split * 0.30, upper_ratio, "bar", min_area=min_area),
        ]
    elif principle == "undercut_tapered_tower":
        base = box(minx, miny, maxx, maxy)
        undercut = box(minx, miny, minx + width * 0.36, miny + depth * 0.34)
        podium = base.difference(undercut)
        tower = scale(footprint, xfact=taper, yfact=max(0.42, taper * 0.88), origin="centroid")
        tower = translate(tower, xoff=width * shift * 0.25, yoff=-depth * shift * 0.18)
        cap = scale(tower, xfact=max(0.56, taper * 0.82), yfact=max(0.52, taper * 0.78), origin="centroid")
        pieces = [
            _clean_piece("primary_undercut_podium", podium, 0.0, split, "base", clip=footprint, min_area=min_area),
            _clean_piece("primary_tapered_tower", tower, split * 0.72, upper_ratio, last_verb, clip=footprint, min_area=min_area),
            _clean_piece("secondary_tower_cap", cap, max(0.72, upper_ratio - 0.16), 1.0, "taper", clip=footprint, min_area=min_area),
            _rect("secondary_ground_void_marker", footprint, minx, miny, minx + width * 0.24, miny + depth * 0.22, 0.0, split * 0.55, "void", min_area=min_area),
        ]
        oblique_field = build_oblique_envelope_field(
            footprint,
            language_params,
            bottom_fraction=0.0,
            top_fraction=1.0,
        )
        if oblique_field is not None:
            oblique_field_evidence = {
                **oblique_field.evidence,
                "field_parameters": {
                    key: language_params[key]
                    for key in (
                        "plan_control_points", "top_height_controls",
                        "shoulder_fraction", "base_scale_x_ratio", "base_scale_y_ratio",
                        "base_shift_x_ratio", "base_shift_y_ratio",
                        "top_scale_x_ratio", "top_scale_y_ratio",
                        "top_shift_x_ratio", "top_shift_y_ratio",
                    )
                    if key in language_params
                },
            }
    elif principle == "continuous_ribbon_field":
        design_field = build_ribbon_design_field(footprint, language_params)
        if design_field is None:
            return None
        height_ratios = list(design_field.evidence.get("height_profile_ratios") or (0.64, 0.96, 0.70))
        height_wave = float(design_field.evidence.get("height_wave") or 0.0)

        def surface_spec(
            role: str,
            path: list[tuple[float, float]],
            width_profile: list[float],
            bottom: float,
            top: float,
            start_t: float = 0.0,
            end_t: float = 1.0,
        ) -> dict[str, Any]:
            roof_profile: list[float] = []
            for index in range(len(path)):
                local_t = index / max(len(path) - 1, 1)
                t = start_t + (end_t - start_t) * local_t
                if t <= 0.5:
                    factor = height_ratios[0] + (height_ratios[1] - height_ratios[0]) * t * 2.0
                else:
                    factor = height_ratios[1] + (height_ratios[2] - height_ratios[1]) * (t - 0.5) * 2.0
                factor += height_wave * sin(t * 2.0 * pi)
                roof_profile.append(bottom + (top - bottom) * max(0.18, min(0.98, factor)))
            return {
                "role": role,
                "verb": "branch" if "branched" in role else "bend",
                "bottom_fraction": bottom,
                "path_points": [[float(x), float(y)] for x, y in path],
                "path_width_m": sum(width_profile) / max(len(width_profile), 1),
                "path_width_profile_m": [float(value) for value in width_profile],
                "roof_profile": roof_profile,
            }
        if design_field.evidence.get("field_topology") == "branched" and len(design_field.paths) >= 2:
            point_count = min(len(path) for path in design_field.paths)
            branch_ratio = float(design_field.evidence.get("branch_point_ratio") or 0.36)
            split_index = max(1, min(point_count - 2, round(branch_ratio * (point_count - 1))))
            trunk_path = [
                (
                    sum(path[index][0] for path in design_field.paths) / len(design_field.paths),
                    sum(path[index][1] for path in design_field.paths) / len(design_field.paths),
                )
                for index in range(split_index + 1)
            ]
            trunk_profile = [
                max(profile[index] for profile in design_field.half_width_profiles) * 1.18
                for index in range(split_index + 1)
            ]
            pieces = [
                _ribbon(
                    "primary_branched_ribbon_trunk",
                    footprint,
                    trunk_path,
                    sum(trunk_profile) / len(trunk_profile),
                    0.0,
                    max(0.84, design_field.vertical_bands[len(design_field.vertical_bands) // 2][1]),
                    "bend",
                    min_area=min_area,
                    width_profile=trunk_profile,
                )
            ]
            trunk_top = max(0.84, design_field.vertical_bands[len(design_field.vertical_bands) // 2][1])
            surface_field_specs.append(surface_spec(
                "primary_branched_ribbon_trunk",
                trunk_path,
                trunk_profile,
                0.0,
                trunk_top,
                0.0,
                split_index / max(point_count - 1, 1),
            ))
            for arm_index, lane_index in enumerate((0, len(design_field.paths) - 1)):
                path = list(design_field.paths[lane_index][split_index:])
                profile = list(design_field.half_width_profiles[lane_index][split_index:])
                arm_role = f"primary_branched_ribbon_arm_{arm_index}"
                arm_top = max(0.84, design_field.vertical_bands[lane_index][1])
                pieces.append(_ribbon(
                    arm_role,
                    footprint,
                    path,
                    sum(profile) / len(profile),
                    0.0,
                    arm_top,
                    "branch",
                    min_area=min_area,
                    width_profile=profile,
                ))
                surface_field_specs.append(surface_spec(
                    arm_role,
                    path,
                    profile,
                    0.0,
                    arm_top,
                    split_index / max(point_count - 1, 1),
                    1.0,
                ))
            # A branch is one continuous occupiable solid, not three
            # translucent boxes that happen to overlap.  Keep the individual
            # trunk/arm surface specs for the profiled roof and VLM evidence,
            # but union their conservative legal/FAR proxy into one volume.
            branch_pieces = [piece for piece in pieces if piece is not None]
            if branch_pieces:
                raw_proxy = unary_union([piece.footprint for piece in branch_pieces])
                proxy = _continuous_field_proxy(
                    raw_proxy,
                    clip=footprint,
                    min_area=min_area,
                )
                if proxy is None:
                    proxy = raw_proxy
                merged = _clean_piece(
                    "primary_branched_ribbon_field",
                    proxy,
                    min(piece.bottom_fraction for piece in branch_pieces),
                    max(piece.top_fraction for piece in branch_pieces),
                    "bend",
                    clip=footprint,
                    min_area=min_area,
                )
                pieces = [merged] if merged is not None else branch_pieces
        else:
            pieces = []
            for index, (path, half_width, width_profile, band) in enumerate(zip(
                design_field.paths,
                design_field.half_widths,
                design_field.half_width_profiles,
                design_field.vertical_bands,
            )):
                role_prefix = "primary" if index < 2 else "secondary"
                role = f"{role_prefix}_continuous_ribbon_lane_{index}"
                pieces.append(_ribbon(
                    role,
                    footprint,
                    list(path),
                    half_width,
                    band[0],
                    band[1],
                    "bend",
                    min_area=min_area,
                    width_profile=width_profile,
                ))
                surface_field_specs.append(surface_spec(
                    role, list(path), list(width_profile), band[0], band[1],
                ))
    elif principle == "torqued_stack":
        torque_angle = max(18.0, min(42.0, abs(angle)))
        torque_shift = max(0.18, min(0.34, abs(shift)))
        tiers = (
            (0.0, 0.38, 0.92, -1.0, -0.75),
            (0.34, 0.70, 0.74, 1.0, 0.0),
            (0.66, 1.0, 0.56, -1.0, 0.75),
        )
        for index, (bottom, top, factor, xsign, angle_factor) in enumerate(tiers):
            plate = scale(footprint, xfact=factor, yfact=max(0.42, factor * 0.86), origin="centroid")
            plate = translate(
                plate,
                xoff=xsign * width * torque_shift * (0.30 + index * 0.10),
                yoff=-xsign * depth * torque_shift * (0.14 + index * 0.05),
            )
            pieces.append(_rot(_role(f"primary_torqued_plate_{index}", genome), footprint, plate, torque_angle * angle_factor, bottom, top, "shift", min_area=min_area))
    elif principle == "stacked_shifted_platforms":
        if str(genome.get("family") or "") == "array_cluster":
            pieces.append(_rect(_role("primary_shifted_platform_0", genome), footprint, minx, miny, maxx, maxy, 0.0, 0.22, "base", min_area=min_area))
            centers = ((-0.22, -0.14), (0.20, 0.14))
            for index, (xoff, yoff) in enumerate(centers, start=1):
                block = box(
                    cx + width * xoff - width * 0.23,
                    cy + depth * yoff - depth * 0.22,
                    cx + width * xoff + width * 0.23,
                    cy + depth * yoff + depth * 0.22,
                )
                pieces.append(_clean_piece(
                    _role(f"primary_shifted_platform_{index}", genome),
                    block,
                    0.18,
                    (0.70, 1.0)[index - 1],
                    "array",
                    clip=footprint,
                    min_area=min_area,
                ))
        else:
            # A stack graph is an occupiable stepped section, not unrelated
            # floating cuboids. The agent controls tier count, shrink and
            # direction; this grammar projects that rule onto the parcel.
            tier_count = int(round(_param(language_params, ("levels", "n"), 3.0, 3.0, 4.0)))
            cascade_axis = str(language_params.get("slide_axis") or language_params.get("axis") or "x").lower()
            upper_ratio = _param(language_params, ("upper_ratio", "top_ratio"), 0.76, 0.62, 0.88)
            for index in range(tier_count):
                progress = index / max(tier_count - 1, 1)
                bottom = index / tier_count
                top = (index + 1) / tier_count
                factor = max(0.52, 1.0 - (1.0 - upper_ratio) * progress)
                plate = scale(footprint, xfact=factor, yfact=max(0.50, factor * 0.96), origin="centroid")
                run = shift * progress * 0.72
                plate = translate(
                    plate,
                    xoff=width * run if cascade_axis == "x" else 0.0,
                    yoff=depth * run if cascade_axis == "y" else 0.0,
                )
                pieces.append(_clean_piece(
                    _role(f"primary_capacity_terrace_tier_{index}", genome),
                    plate,
                    bottom,
                    top,
                    "stack",
                    clip=footprint,
                    min_area=min_area,
                ))
    elif principle == "folded_section":
        # A fold must be an authored object inside the parcel, not a roof drawn
        # over a 100%-coverage site slab.  The latter made every folded seed
        # fail the creative coverage gate and silently removed this entire
        # architectural language from the archive.
        plinth = scale(
            footprint,
            xfact=_param(language_params, ("x_ratio",), 0.84, 0.68, 0.90),
            yfact=_param(language_params, ("y_ratio",), 0.80, 0.64, 0.88),
            origin="centroid",
        )
        pminx, pminy, pmaxx, pmaxy, pwidth, _ = _bounds(plinth)
        pcx = plinth.centroid.x
        pieces = [
            _clean_piece(_role("primary_folded_base", genome), plinth, 0.0, 0.38, "base", clip=footprint, min_area=min_area),
            _rect(_role("primary_folded_low_plane", genome), plinth, pminx, pminy, pcx + pwidth * 0.04, pmaxy, 0.34, 0.70, "sloped_roof_mass", min_area=min_area),
            _rect(_role("primary_folded_high_plane", genome), plinth, pcx - pwidth * 0.04, pminy, pmaxx, pmaxy, 0.66, 1.0, "sloped_roof_mass", min_area=min_area),
        ]
        section_field = build_section_loft_field(plinth, language_params)
        if section_field is not None:
            section_field_evidence = {
                **section_field.evidence,
                "field_parameters": {
                    key: language_params[key]
                    for key in (
                        "axis", "field_samples", "longitudinal_wave", "twist", "control_points",
                        "section_interpolation",
                    )
                    if key in language_params
                },
            }
    elif principle == "terraced_ribbon_section":
        # A readable early-massing fold is a common plinth plus two roof
        # boxes meeting along one datum. The previous two full-plan polygons
        # occupied almost the same plan and produced crossed linework rather
        # than a legible section.
        pieces = [
            _rect(_role("primary_folded_base", genome), footprint, minx, miny, maxx, maxy, 0.0, 0.38, "base", min_area=min_area),
            _rect(_role("primary_folded_low_plane", genome), footprint, minx, miny, cx + width * 0.03, maxy, 0.34, 0.70, "sloped_roof_mass", min_area=min_area),
            _rect(_role("primary_folded_high_plane", genome), footprint, cx - width * 0.03, miny, maxx, maxy, 0.66, 1.0, "sloped_roof_mass", min_area=min_area),
        ]
    elif principle == "carved_atrium":
        court_w = width * void_ratio
        court_d = depth * void_ratio
        pieces = [
            _rect("primary_atrium_north_bar", footprint, minx, cy + court_d / 2, maxx, maxy, 0.0, split, "courtyard", min_area=min_area),
            _rect("primary_atrium_south_bar", footprint, minx, miny, maxx, cy - court_d / 2, 0.0, upper_ratio, "courtyard", min_area=min_area),
            _rect("secondary_atrium_liner", footprint, cx - court_w / 2, miny, cx + court_w / 2, maxy, split * 0.72, 1.0, "void", min_area=min_area),
            _rect("secondary_atrium_bridge", footprint, minx, cy - depth * 0.06, maxx, cy + depth * 0.06, max(split, 0.48), 1.0, "bridge", min_area=min_area),
        ]
    elif principle == "split_bridge_connector":
        gap = width * max(0.05, min(0.22, shift))
        # Keep the two inhabited wings genuinely separate and let a single,
        # short connector resolve the composition.  The old implementation
        # drew a diagonal bar across the entire site and added a full-depth
        # core through the same space.  That created four mutually colliding
        # boxes, so every authored bridge language failed the geometry
        # coherence gate before VLM review.
        #
        # These dimensions are ratios supplied by the language graph/site
        # envelope, not a card-specific footprint template.  The bearing is
        # intentionally small: enough to make one connected architectural
        # diagram, but not enough to turn the bridge into a third full wing.
        bearing = width * _param(language_params, ("bearing_ratio",), 0.055, 0.035, 0.085)
        bridge_half_depth = depth * _param(language_params, ("bridge_width_ratio", "factor"), 0.065, 0.045, 0.095)
        bridge_angle = max(-18.0, min(18.0, angle))
        pieces = [
            _rect(_role("primary_split_wing_a", genome), footprint, minx, miny, cx - gap, maxy, 0.0, upper_ratio, "split", min_area=min_area),
            _rect(_role("primary_split_wing_b", genome), footprint, cx + gap, miny, maxx, maxy, split * 0.65, 1.0, "split", min_area=min_area),
            _rot(
                _role("primary_diagonal_bridge_connector", genome),
                footprint,
                box(
                    cx - gap - bearing,
                    cy - bridge_half_depth,
                    cx + gap + bearing,
                    cy + bridge_half_depth,
                ),
                bridge_angle,
                max(split, 0.48),
                min(1.0, max(split, 0.48) + 0.30),
                "diagonal_connect",
                min_area=min_area,
            ),
        ]
    elif principle == "carved_monolith":
        cut = box(cx - width * void_ratio / 2, cy - depth * void_ratio / 2, cx + width * void_ratio / 2, cy + depth * void_ratio / 2)
        shell = footprint.difference(cut)
        pieces = [
            _clean_piece(_role("primary_carved_shell", genome), shell, 0.0, upper_ratio, "cave", clip=footprint, min_area=min_area),
            _ribbon(_role("secondary_void_liner_spine", genome), footprint, [(cx, miny), (cx, maxy)], width * 0.045, split, 1.0, "void", min_area=min_area),
            _rect(_role("secondary_monolith_cap", genome), footprint, minx, maxy - depth * 0.18, maxx, maxy, max(split, 0.52), 1.0, "cap", min_area=min_area),
        ]

    volumes = tuple(piece for piece in pieces if piece is not None)
    # A continuous field may be one watertight/unioned legal solid while its
    # trunk and arms remain separate editable surface patches.  Requiring
    # three solids here silently discarded that clean representation and sent
    # it back to the legacy two-box bend fallback.
    minimum_volume_count = 1 if principle == "continuous_ribbon_field" else 3
    if len(volumes) < minimum_volume_count:
        return None
    roles = [volume.role for volume in volumes]
    genome_strategy_evidence = {
        "void_strategy": str(genome.get("void_strategy") or ""),
        "vertical_strategy": str(genome.get("vertical_strategy") or ""),
        "connector_strategy": str(genome.get("connector_strategy") or ""),
        "silhouette_strategy": str(genome.get("silhouette_strategy") or ""),
        "stair_like_risk": str(genome.get("stair_like_risk") or ""),
        "inference_source": str(genome.get("inference_source") or ""),
    }
    evidence = {
        "schema_version": "arr.maas.architectural_ambition.v1",
        "formal_principle": principle,
        "dominant_gesture": str(dominant_gesture or principle),
        "has_formal_principle": True,
        "has_dominant_gesture": True,
        "implemented_volume_roles": roles,
        "massing_genome_schema_version": str(genome.get("schema_version") or ""),
        "genome_strategy_evidence": genome_strategy_evidence,
        "void_strategy": genome_strategy_evidence["void_strategy"],
        "vertical_strategy": genome_strategy_evidence["vertical_strategy"],
        "connector_strategy": genome_strategy_evidence["connector_strategy"],
        "silhouette_strategy": genome_strategy_evidence["silhouette_strategy"],
        "stair_like_risk": genome_strategy_evidence["stair_like_risk"],
        "silhouette_strength": 1.0 if any("tower" in role or "torqued" in role or "folded" in role for role in roles) else 0.78,
        "sectional_diagram_clarity": 1.0 if len({(round(v.bottom_fraction, 2), round(v.top_fraction, 2)) for v in volumes}) >= 3 else 0.72,
        "podium_or_ground_relationship": any("podium" in role or "ground" in role or "base" in role for role in roles),
        "architecture_grade_pass": True,
    }
    if principle == "continuous_ribbon_field" and design_field is not None:
        evidence["site_design_field"] = {
            **design_field.evidence,
            "surface_field_specs": surface_field_specs,
        }
    if section_field_evidence:
        evidence["site_section_field"] = section_field_evidence
    if oblique_field_evidence:
        evidence["site_oblique_envelope"] = oblique_field_evidence
    return FormalPrincipleResult(principle=principle, volumes=volumes, evidence=evidence)


__all__ = [
    "CANONICAL_FORMAL_PRINCIPLES",
    "FORMAL_PRINCIPLE_ALIASES",
    "FormalPrincipleResult",
    "compile_formal_principle_volumes",
    "normalize_formal_principle",
]
