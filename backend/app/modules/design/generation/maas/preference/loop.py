"""Image-backed second-stage preference loop for MAAS review candidates."""

from __future__ import annotations

from backend.app.modules.design.generation import paths as _design_paths

import os
import re
import tempfile
import hashlib
import json
import uuid
from math import cos, isfinite, radians, sin, sqrt
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from shapely.geometry import Point, shape

from backend.app.modules.design.generation.maas.preference.mesh_rasterizer import RasterTriangle, rasterize_depth_tested_triangles

from backend.app.modules.design.generation.maas.morphology_operators import largest_polygon
from backend.app.modules.design.generation.maas.geometry_language.floorwise_visual_projection import projected_surface_visual_hash
from backend.app.modules.design.generation.maas.geometry_language.projected_visual_contract import CertifiedMassArtifact, CERTIFICATE_SCHEMA, FINAL_AUTHORITY_CERTIFICATION_MODE, FINAL_CERTIFICATE_SCHEMA, RENDERER_COORDINATE_CONTRACT_VERSION, exact_triangle_payload_hash, normalize_persisted_projected_visual_artifact, projected_visual_z_coordinate_mode
from backend.app.modules.design.generation.maas.preference.concept_schema import build_preference_distillation
from backend.app.modules.design.generation.maas.preference.reference_corpus import default_reference_root, load_reference_tree, match_reference_context
from backend.app.modules.design.generation.maas.preference.vlm_scorer import VLM_PROMPT_CONTRACT_VERSION, score_candidate_with_openai_vlm
from backend.app.modules.design.generation.maas.source_geometry.ir import SourceSurface
from backend.app.modules.design.generation.services.site_geometry import geojson_to_polygon, utm_to_wgs84, wgs84_to_utm


Feature = dict[str, Any]


@dataclass(frozen=True)
class PreferenceLoopCallbacks:
    design_review_quality_key: Callable[[Feature], tuple[float, ...]]
    final_mass_stage_parking_pass: Callable[[Feature], bool]
    has_review_source_geometry: Callable[[Feature], bool]
    is_plain_capacity_anchor: Callable[[Feature], bool]
    is_reviewable_architectural_mass: Callable[[Feature], bool]
    source_family: Callable[[Feature], str]


def preference_score(feature: Feature) -> float:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    preference = props.get("preference_distillation") if isinstance(props.get("preference_distillation"), dict) else {}
    return float(preference.get("distilled_preference_score") or 0.0)


def preference_vlm_scored(feature: Feature) -> bool:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    preference = props.get("preference_distillation") if isinstance(props.get("preference_distillation"), dict) else {}
    return preference.get("mode") == "vlm_scored" and preference.get("vlm_status") == "scored"


def preference_loop_config(parking_options: dict[str, Any] | None) -> dict[str, Any]:
    options = parking_options or {}
    raw = options.get("maas_preference_loop") if isinstance(options.get("maas_preference_loop"), dict) else {}
    enabled = bool(raw.get("enabled") or raw.get("require_vlm"))
    require_vlm = bool(raw.get("require_vlm"))
    min_final_raw = raw.get("min_final_vlm_scored") or os.getenv("MAAS_PREFERENCE_LOOP_MIN_FINAL_VLM")
    return {
        "enabled": enabled,
        "require_vlm": require_vlm,
        "top_k": max(1, int(raw.get("top_k") or 40)),
        "parallel_workers": max(1, int(raw.get("parallel_workers") or os.getenv("MAAS_PREFERENCE_LOOP_WORKERS") or 4)),
        "min_final_vlm_scored": max(0, int(min_final_raw if min_final_raw is not None else (16 if require_vlm else 0))),
        "model": raw.get("model") if isinstance(raw.get("model"), str) else os.getenv("MAAS_PREFERENCE_VLM_MODEL", ""),
        "reference_root": raw.get("reference_root") if isinstance(raw.get("reference_root"), str) else "",
        "image_uri": raw.get("image_uri") if isinstance(raw.get("image_uri"), str) else "",
        "cache_dir": raw.get("cache_dir") if isinstance(raw.get("cache_dir"), str) else os.getenv(
            "MAAS_PREFERENCE_VLM_CACHE_DIR", "docs/ai-session-memory/reference-corpus/vlm-cache"
        ),
    }


def preference_reference_root(config: dict[str, Any]) -> Path:
    raw = str(config.get("reference_root") or "").strip()
    if raw:
        path = Path(raw).expanduser()
        if path.is_absolute():
            return path
        workspace_root = _design_paths.workspace_root()
        return workspace_root / path
    return default_reference_root()


def _opaque_profiled_surface_fill(vertices: list[list[float]]) -> tuple[int, int, int, int]:
    """Return one opaque, normal-shaded material for every profiled solid skin.

    Program-section roofs used to be drawn with alpha=150 while recursive
    kernel meshes used alpha=255.  Rear faces therefore showed through an
    otherwise closed gable/folded/sawtooth envelope and made those candidates
    look like a different wireframe representation.  Both representations are
    authoritative solid skins, so the preview must use the same opaque
    material contract for both.
    """
    if len(vertices) < 3:
        return (246, 142, 58, 255)
    a, b, c = vertices[:3]
    ux, uy, uz = float(b[0]) - float(a[0]), float(b[1]) - float(a[1]), float(b[2]) - float(a[2])
    vx, vy, vz = float(c[0]) - float(a[0]), float(c[1]) - float(a[1]), float(c[2]) - float(a[2])
    nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    magnitude = max(sqrt(nx * nx + ny * ny + nz * nz), 1e-12)
    normal = (nx / magnitude, ny / magnitude, nz / magnitude)
    light = (0.34, -0.42, 0.84)
    intensity = 0.52 + 0.42 * abs(sum(normal[index] * light[index] for index in range(3)))
    return (
        min(255, int(250 * intensity)),
        min(220, int(151 * intensity)),
        min(150, int(62 * intensity)),
        255,
    )


def _display_projection_frame(
    vertices: list[list[float]],
    *,
    angle: float,
    top_view: bool,
    view_width: int,
    view_height: int,
) -> tuple[Callable[[tuple[float, float], float], tuple[float, float]], tuple[float, float]]:
    """Build a display-only camera from immutable visual-vertex XYZ bounds."""

    theta = radians(angle)

    def raw(point: tuple[float, float], z: float) -> tuple[float, float]:
        rx = float(point[0]) * cos(theta) - float(point[1]) * sin(theta)
        ry = float(point[0]) * sin(theta) + float(point[1]) * cos(theta)
        return (rx, -ry) if top_view else (rx, ry * 0.34 - float(z))

    projected = [raw((vertex[0], vertex[1]), vertex[2]) for vertex in vertices]
    min_px = min(point[0] for point in projected)
    max_px = max(point[0] for point in projected)
    min_py = min(point[1] for point in projected)
    max_py = max(point[1] for point in projected)
    span_x = max(max_px - min_px, 1e-9)
    span_y = max(max_py - min_py, 1e-9)
    scale = min((view_width - 70) / span_x, (view_height - 70) / span_y)
    center_x = (min_px + max_px) / 2.0
    center_y = (min_py + max_py) / 2.0

    def project(point: tuple[float, float], z: float = 0.0) -> tuple[float, float]:
        px, py = raw(point, z)
        return (
            view_width * 0.50 + (px - center_x) * scale,
            view_height * 0.55 + (py - center_y) * scale,
        )

    return project, (
        sum(float(vertex[0]) for vertex in vertices) / len(vertices),
        sum(float(vertex[1]) for vertex in vertices) / len(vertices),
    )


def feature_preview_png(feature: Feature, output_dir: Path) -> Path:
    """Write a small temporary massing preview for VLM scoring."""
    try:
        from PIL import Image, ImageDraw
    except Exception as exc:
        raise ValueError(f"Pillow is required for MAAS preference VLM previews: {exc}") from exc
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    _require_certified_authored_visual(
        props,
        feature_geometry=feature.get("geometry"),
    )
    site_boundary = None
    site_boundary_geometry = props.get("site_boundary_geometry")
    if isinstance(site_boundary_geometry, dict):
        try:
            candidate_boundary = largest_polygon(shape(site_boundary_geometry))
            if candidate_boundary is not None and not candidate_boundary.is_empty:
                site_boundary = candidate_boundary
        except Exception:
            site_boundary = None
    site_access_coords: list[tuple[float, float]] = []
    site_access_geometry = props.get("site_access_geometry")
    if isinstance(site_access_geometry, dict):
        try:
            access_line = shape(site_access_geometry)
            site_access_coords = [(float(x), float(y)) for x, y in access_line.coords]
        except Exception:
            site_access_coords = []
    volumes = props.get("mass_volumes")
    if not isinstance(volumes, list) or not volumes:
        volumes = [{"geometry": feature.get("geometry"), "bottom_height": 0.0, "top_height": props.get("height") or 8.4}]
    explicit_surfaces: list[dict[str, Any]] = []
    for surface in props.get("source_surfaces") or []:
        if not isinstance(surface, dict) or not str(surface.get("surface_type") or "").startswith("profiled_"):
            continue
        vertices = _surface_vertices_world(surface, feature)
        if vertices and len(vertices) >= 3:
            explicit_surfaces.append(surface)
    profiled_roles = {str(item.get("volume_role") or "") for item in explicit_surfaces}
    rings: list[tuple[list[tuple[float, float]], float, float, str]] = []
    for volume in volumes:
        if not isinstance(volume, dict):
            continue
        geometry = volume.get("geometry")
        try:
            geom = shape(geometry) if isinstance(geometry, dict) else None
        except Exception:
            geom = None
        if geom is None or geom.is_empty:
            continue
        polygon = largest_polygon(geom)
        coords = [(float(x), float(y)) for x, y in list(polygon.exterior.coords)]
        if len(coords) >= 4:
            rings.append((
                coords,
                float(volume.get("bottom_height") or 0.0),
                float(volume.get("top_height") or props.get("height") or 8.4),
                str(volume.get("role") or ""),
            ))
    if not rings:
        raise ValueError("candidate has no previewable geometry")
    surface_records = [
        (surface, _surface_vertices_world(surface, feature))
        for surface in explicit_surfaces
    ]
    surface_records = [record for record in surface_records if len(record[1]) >= 3]
    visual_vertices = [
        [float(value) for value in vertex]
        for _surface, vertices in surface_records
        for vertex in vertices
    ]
    if not visual_vertices:
        visual_vertices = [
            [float(x), float(y), float(z)]
            for coords, bottom, top, _role in rings
            for x, y in coords
            for z in (bottom, top)
        ]
    xs = [x for coords, _, _, _ in rings for x, _ in coords]
    ys = [y for coords, _, _, _ in rings for _, y in coords]
    site_coords = (
        [(float(x), float(y)) for x, y in site_boundary.exterior.coords]
        if site_boundary is not None
        else []
    )
    xs.extend(x for x, _ in site_coords)
    ys.extend(y for _, y in site_coords)
    xs.extend(float(vertex[0]) for surface in explicit_surfaces for vertex in _surface_vertices_world(surface, feature))
    ys.extend(float(vertex[1]) for surface in explicit_surfaces for vertex in _surface_vertices_world(surface, feature))
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    # A single isometric view hid rear-side collisions and made the VLM reward
    # silhouettes that failed from another direction.  LayoutVLM/VLM3D-style
    # test-time criticism needs spatially redundant evidence, so score a fixed
    # four-view contact sheet for every candidate.
    width, height = 720, 520
    view_width, view_height = 350, 235
    image = Image.new("RGB", (width, height), "#f7f9fb")
    draw = ImageDraw.Draw(image, "RGBA")
    shape_name = str(props.get("mass_shape") or props.get("variant_id") or "maas")
    views = (
        ("isometric", 35.0, False, 0, 0),
        ("opposite", 215.0, False, 360, 0),
        ("front", 0.0, False, 0, 250),
        ("top", 0.0, True, 360, 250),
    )
    for label, angle, top_view, ox, oy in views:
        theta = radians(angle)
        local_project, (camera_cx, camera_cy) = _display_projection_frame(
            visual_vertices,
            angle=angle,
            top_view=top_view,
            view_width=view_width,
            view_height=view_height,
        )

        def project(point: tuple[float, float], z: float = 0.0) -> tuple[float, float]:
            px, py = local_project(point, z)
            return ox + px, oy + py

        def camera_depth(vertex: list[float]) -> float:
            """Painter depth matching the fixed orthographic preview camera."""
            x = float(vertex[0]) - camera_cx
            y = float(vertex[1]) - camera_cy
            ry = x * sin(theta) + y * cos(theta)
            return float(vertex[2]) if top_view else ry + float(vertex[2]) * 0.12

        draw.rectangle((ox + 5, oy + 5, ox + view_width - 5, oy + view_height - 5), outline=(203, 213, 225, 255))
        draw.text((ox + 14, oy + 12), label, fill=(71, 85, 105, 255))
        if site_coords:
            boundary_points = [project(point, 0.0) for point in site_coords]
            draw.polygon(boundary_points, fill=(52, 211, 153, 18))
            draw.line(boundary_points, fill=(16, 185, 129, 210), width=2, joint="curve")
        if site_access_coords:
            access_points = [project(point, 0.02) for point in site_access_coords]
            draw.line(access_points, fill=(37, 99, 235, 245), width=5)
        for coords, bottom, top, role in sorted(rings, key=lambda item: item[1]):
            if role in profiled_roles:
                continue
            top_points = [project(point, 0.0 if top_view else top) for point in coords]
            base_points = [project(point, 0.0 if top_view else bottom) for point in coords]
            if not top_view:
                for index in range(len(coords) - 1):
                    side = [base_points[index], base_points[index + 1], top_points[index + 1], top_points[index]]
                    left, right = coords[index], coords[index + 1]
                    side_vertices = [
                        [left[0], left[1], bottom],
                        [right[0], right[1], bottom],
                        [right[0], right[1], top],
                        [left[0], left[1], top],
                    ]
                    draw.polygon(side, fill=_opaque_profiled_surface_fill(side_vertices), outline=None)
            top_vertices = [[point[0], point[1], top] for point in coords]
            draw.polygon(top_points, fill=_opaque_profiled_surface_fill(top_vertices), outline=None)
        recursive_triangles: list[RasterTriangle] = []
        for surface, vertices in sorted(
            surface_records,
            key=lambda record: sum(camera_depth(vertex) for vertex in record[1]) / len(record[1]),
        ):
            points = [project((float(v[0]), float(v[1])), 0.0 if top_view else float(v[2])) for v in vertices]
            surface_type = str(surface.get("surface_type") or "")
            is_recursive_mesh = surface_type == "profiled_recursive_solid_mesh"
            profiled_fill = _opaque_profiled_surface_fill(vertices)
            if is_recursive_mesh:
                if len(points) == 3:
                    color = tuple(int(value) for value in profiled_fill)
                    if len(color) == 3:
                        color = (*color, 255)
                    recursive_triangles.append(RasterTriangle(
                        points=(points[0], points[1], points[2]),
                        depths=tuple(camera_depth(vertex) for vertex in vertices[:3]),
                        color=color,
                    ))
                continue
            draw.polygon(
                points,
                # Every profiled representation is a closed architectural
                # skin.  Opaque depth-ordered faces keep program-section
                # gables/folds and recursive compiler meshes visually
                # comparable instead of mixing solid and X-ray modes.
                fill=profiled_fill,
                # Patch/triangle edges stay in the typed graph payload.  They
                # are not a second visual language in the rendered evidence.
                outline=None,
            )
        if recursive_triangles:
            rasterize_depth_tested_triangles(
                image,
                recursive_triangles,
                clip_box=(ox + 6, oy + 6, ox + view_width - 6, oy + view_height - 6),
            )
        # Do not redraw every semantic-normal patch edge.  Those edges include
        # occluded back faces and reintroduce the wireframe failure even after
        # correct face ordering.  Multi-view silhouettes plus shaded opaque
        # faces are the VLM evidence; the typed patch IDs stay in JSON.
        # A painter renderer cannot reliably determine whether a crease on a
        # rear triangle is occluded by a concave front face. Drawing those
        # edges produced detached orange "wires" that were not geometry. The
        # opaque, normal-shaded manifold faces are the visual authority; exact
        # edge topology remains available in the typed mesh/graph payload.
    draw.rectangle((8, height - 28, width - 8, height - 5), fill=(247, 249, 251, 245))
    draw.text((14, height - 24), shape_name[:80], fill=(15, 23, 42, 255))
    output_dir.mkdir(parents=True, exist_ok=True)
    unique_suffix = f"{id(feature):x}"
    path = output_dir / f"{re.sub(r'[^A-Za-z0-9_.-]+', '_', shape_name)[:68]}_{unique_suffix}.png"
    temporary_path = path.with_suffix(".tmp.png")
    image.save(temporary_path)
    temporary_path.replace(path)
    return path


def _require_certified_authored_visual(
    props: dict[str, Any],
    *,
    feature_geometry: Any = None,
) -> None:
    raw_surfaces = props.get("source_surfaces")
    raw_surfaces = raw_surfaces if isinstance(raw_surfaces, list) else []
    certified_records = [
        record for record in raw_surfaces if isinstance(record, dict)
    ]
    profiled_records = [
        record
        for record in certified_records
        if str(record.get("surface_type") or "").startswith("profiled_")
    ]
    signature = (
        props.get("source_signature")
        if isinstance(props.get("source_signature"), dict)
        else {}
    )
    bridge = (
        signature.get("geometry_program_bridge_evidence")
        if isinstance(signature.get("geometry_program_bridge_evidence"), dict)
        else {}
    )
    authored_profiled = bool(
        profiled_records
        or int(bridge.get("raw_mesh_triangle_count") or 0) > 0
    )
    if not authored_profiled:
        return

    model = props.get("maas_model")
    model = model if isinstance(model, dict) else {}
    certificate = props.get("floorwise_visual_projection")
    if not isinstance(certificate, dict):
        certificate = model.get("floorwise_visual_projection")
    failure = "authored profiled visual mesh requires certified nonempty projection"
    artifact = (
        props.get("geometry_artifact")
        if isinstance(props.get("geometry_artifact"), dict)
        else {}
    )
    if artifact:
        artifact = normalize_persisted_projected_visual_artifact(artifact)
    artifact_certificate = artifact.get("projectedVisualCertificate")
    certified_mass_artifact = None
    if (
        isinstance(artifact_certificate, dict)
        and artifact_certificate.get("certification_mode")
        == FINAL_AUTHORITY_CERTIFICATION_MODE
    ):
        try:
            certified_mass_artifact = CertifiedMassArtifact.load(
                artifact,
                authority_context=(
                    props.get("final_semantic_anchor")
                    if isinstance(props.get("final_semantic_anchor"), dict)
                    else {}
                ),
            )
        except ValueError as exc:
            raise ValueError(f"{failure}:{exc}") from None
        artifact = certified_mass_artifact.payload()
        certificate = certified_mass_artifact.certificate()
    elif not isinstance(certificate, dict):
        certificate = artifact_certificate
    expected_certificate_schema = (
        FINAL_CERTIFICATE_SCHEMA
        if isinstance(certificate, dict)
        and certificate.get("certification_mode")
        == FINAL_AUTHORITY_CERTIFICATION_MODE
        else CERTIFICATE_SCHEMA
    )
    artifact_hash_mismatch = bool(
        artifact
        and str(artifact.get("projectedVisualGeometryHash") or "")
        != str(certificate.get("visual_hash") or "")
    ) if isinstance(certificate, dict) else bool(artifact)
    invalid_certificate = (
        not isinstance(certificate, dict)
        or certificate.get("schema_version")
        != expected_certificate_schema
        or certificate.get("status") != "certified"
        or certificate.get("hard_pass") is not True
        or not str(certificate.get("visual_hash") or "")
        or int(certificate.get("projected_surface_count") or 0)
        != len(certified_records)
        or not profiled_records
        or artifact_hash_mismatch
    )
    if invalid_certificate:
        certificate = certificate if isinstance(certificate, dict) else {}
        raise ValueError(
            f"{failure}:"
            f"schema={certificate.get('schema_version')!s}:"
            f"status={certificate.get('status')!s}:"
            f"hard_pass={certificate.get('hard_pass')!s}:"
            f"visual_hash={bool(str(certificate.get('visual_hash') or ''))}:"
            f"projected_surface_count={int(certificate.get('projected_surface_count') or 0)}:"
            f"certified_record_count={len(certified_records)}:"
            f"profiled_record_count={len(profiled_records)}:"
            f"artifact_hash_mismatch={artifact_hash_mismatch}"
        )
    try:
        surfaces = tuple(
            SourceSurface(
                role=str(record.get("role") or ""),
                volume_role=str(record.get("volume_role") or ""),
                verb=str(record.get("verb") or ""),
                surface_type=str(record.get("surface_type") or ""),
                vertices_m=tuple(
                    tuple(float(value) for value in vertex)
                    for vertex in record.get("vertices_m") or ()
                ),
                operator=str(record.get("operator") or "extrude"),
                semantic_patch_id=str(record.get("semantic_patch_id") or ""),
            )
            for record in certified_records
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{failure}:surface_decode:{exc}") from None
    if (
        any(len(surface.vertices_m) != 3 for surface in surfaces)
    ):
        nontriangle_counts = sorted({
            len(surface.vertices_m)
            for surface in surfaces
            if len(surface.vertices_m) != 3
        })
        raise ValueError(
            f"{failure}:nontriangle_vertex_counts={nontriangle_counts}"
        )
    if (
        certificate.get("certification_mode")
        == "authored_projected_surface_authority"
    ):
        try:
            semantic_anchor = (
                props.get("final_semantic_anchor")
                if isinstance(props.get("final_semantic_anchor"), dict)
                else {}
            )
            certified_origin = certificate.get(
                "source_footprint_centroid_utm"
            )
            if (
                not isinstance(certified_origin, list)
                or len(certified_origin) != 2
                or not isinstance(feature_geometry, dict)
            ):
                raise ValueError(failure)
            feature_origin = shape(feature_geometry).centroid
            if (
                abs(
                    float(feature_origin.x)
                    - float(certified_origin[0])
                )
                > 1e-7
                or abs(
                    float(feature_origin.y)
                    - float(certified_origin[1])
                )
                > 1e-7
            ):
                raise ValueError(failure)
            validated = (
                certified_mass_artifact.validated_visual
                if certified_mass_artifact is not None
                else None
            )
            surface_records = [
                {
                    "role": surface.role,
                    "volume_role": surface.volume_role,
                    "verb": surface.verb,
                    "surface_type": surface.surface_type,
                    "vertices_m": [
                        [float(x), float(y), float(z)]
                        for x, y, z in surface.vertices_m
                    ],
                    "operator": surface.operator,
                    "semantic_patch_id": surface.semantic_patch_id,
                }
                for surface in surfaces
            ]
            if (
                validated is None
                or exact_triangle_payload_hash(surface_records)
                != str(artifact.get("projectedVisualPayloadHash") or "")
            ):
                raise ValueError(failure)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{failure}:final_authority_validation:{exc}"
            ) from None
        return
    if (
        projected_surface_visual_hash(surfaces)
        != str(certificate.get("visual_hash") or "")
    ):
        raise ValueError(failure)


def _surface_vertices_world(surface: dict[str, Any], feature: Feature) -> list[list[float]]:
    local = surface.get("vertices_m")
    if not isinstance(local, list) or not local:
        return []
    try:
        props = (
            feature.get("properties")
            if isinstance(feature.get("properties"), dict)
            else {}
        )
        height = float(props.get("height") or 0.0)
        if height <= 0.0 or not isfinite(height):
            raise ValueError
        projected_feature_frame = bool(
            props.get("geometry_artifact")
            or props.get("benchmark_site_area_m2")
        )
        artifact = (
            props.get("geometry_artifact")
            if isinstance(props.get("geometry_artifact"), dict)
            else None
        )
        z_mode = (
            projected_visual_z_coordinate_mode(artifact)
            if artifact
            else "normalized_height_fraction_z"
        )
        if projected_feature_frame:
            origin = shape(feature.get("geometry")).centroid
        else:
            ground = wgs84_to_utm(geojson_to_polygon(feature.get("geometry")))
            origin = ground.centroid
        vertices: list[list[float]] = []
        for raw_vertex in local:
            if not isinstance(raw_vertex, list) or len(raw_vertex) != 3:
                raise ValueError
            x, y, z = (float(value) for value in raw_vertex)
            if not all(isfinite(value) for value in (x, y, z)):
                raise ValueError
            if projected_feature_frame:
                world_x = float(origin.x) + x
                world_y = float(origin.y) + y
            else:
                world = utm_to_wgs84(Point(
                    float(origin.x) + x,
                    float(origin.y) + y,
                ))
                world_x = float(world.x)
                world_y = float(world.y)
            vertices.append([
                round(world_x, 8),
                round(world_y, 8),
                round(
                    z
                    if z_mode == "physical_meter_z"
                    else height * z,
                    4,
                ),
            ])
        return vertices
    except (TypeError, ValueError):
        raise ValueError(
            "certified profiled visual mesh has invalid local coordinates"
        ) from None


def _vlm_cache_key(
    feature: Feature,
    reference_matches: list[dict[str, Any]],
    model: str | None,
    *,
    rendered_png_sha256: str = "",
    renderer_coordinate_contract_version: str = (
        RENDERER_COORDINATE_CONTRACT_VERSION
    ),
) -> str:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    volumes = props.get("mass_volumes") if isinstance(props.get("mass_volumes"), list) else []
    surfaces = props.get("source_surfaces") if isinstance(props.get("source_surfaces"), list) else []
    payload = {
        "schema": "arr.maas.vlm_cache.v4_rendered_png_authority",
        "prompt_contract": VLM_PROMPT_CONTRACT_VERSION,
        "model": model or "",
        "rendered_png_sha256": str(rendered_png_sha256 or ""),
        "renderer_coordinate_contract_version": str(
            renderer_coordinate_contract_version or ""
        ),
        # These fields are part of the scorer prompt and can change a valid
        # judgment even when the rendered solid is byte-for-byte identical.
        # Omitting them allowed a gym/site/review-stage decision to leak into
        # another program through the shared cache.
        "semantic_context": {
            "building_type": props.get("building_type"),
            "program_context": props.get("program_context") or {},
            "site_boundary_source": props.get("site_boundary_source"),
            "site_access_context": props.get("site_access_context") or {},
            "geometry_only_critic_mode": bool(props.get("geometry_only_critic_mode")),
            "portfolio_diversity_context": props.get("portfolio_diversity_context") or {},
        },
        "geometry": feature.get("geometry"),
        "height": props.get("height"),
        "volumes": [
            {
                "geometry": item.get("geometry"),
                "bottom": item.get("bottom_height"),
                "top": item.get("top_height"),
            }
            for item in volumes if isinstance(item, dict)
        ],
        # VLM judges the rendered preview, not only the footprint volumes.
        # Include the actual profiled/mesh vertices so a geometry compiler
        # change cannot inherit a stale score from a former box rendering.
        "surfaces": [
            {
                "role": item.get("role"),
                "volume_role": item.get("volume_role"),
                "verb": item.get("verb"),
                "surface_type": item.get("surface_type"),
                "operator": item.get("operator"),
                "vertices_m": item.get("vertices_m"),
            }
            for item in surfaces if isinstance(item, dict)
        ],
        "references": [
            (item.get("source"), item.get("source_id"), item.get("local_path"))
            for item in reference_matches[:3] if isinstance(item, dict)
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def openai_preview_preference_scorer(*, preview_dir: Path, cache_dir: Path | None = None):
    def score(*, feature: Feature, reference_matches: list[dict[str, Any]], model: str | None = None) -> dict[str, Any]:
        # Always materialize the exact current MASS image, including cache hits.
        # The paid response cache and the chronological execution archive are
        # separate concerns: a cached judgement still needs run-local visual
        # evidence so /design/language can replay what the critic saw.
        image_path = feature_preview_png(feature, preview_dir)
        rendered_png_sha256 = hashlib.sha256(
            image_path.read_bytes()
        ).hexdigest()
        cache_path: Path | None = None
        if cache_dir is not None:
            cache_path = cache_dir / f"{_vlm_cache_key(
                feature,
                reference_matches,
                model,
                rendered_png_sha256=rendered_png_sha256,
                renderer_coordinate_contract_version=(
                    RENDERER_COORDINATE_CONTRACT_VERSION
                ),
            )}.json"
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                if isinstance(cached, dict) and isinstance(cached.get("concept_scores"), dict):
                    return {
                        **cached,
                        "cache_hit": True,
                        "review_image_path": str(image_path.resolve()),
                    }
            except (OSError, ValueError, TypeError):
                pass
        result = score_candidate_with_openai_vlm(
            feature=feature,
            image_path=image_path,
            reference_matches=reference_matches,
            model=model,
        )
        result = {
            **result,
            "cache_hit": False,
            "review_image_path": str(image_path.resolve()),
        }
        if cache_path is not None:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = cache_path.with_suffix(f".{os.getpid()}.{uuid.uuid4().hex}.tmp")
            temporary.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True), encoding="utf-8")
            temporary.replace(cache_path)
        return result

    return score


def apply_preference_loop(
    features: list[Feature],
    *,
    config: dict[str, Any],
    callbacks: PreferenceLoopCallbacks,
    scorer: Any | None = None,
) -> dict[str, Any]:
    if not config.get("enabled"):
        return {
            "schema_version": "arr.maas.preference_loop.v1",
            "enabled": False,
            "status": "not_requested",
        }
    candidate_pool = [
        feature for feature in features
        if callbacks.has_review_source_geometry(feature)
        and callbacks.is_reviewable_architectural_mass(feature)
        and not callbacks.is_plain_capacity_anchor(feature)
        and callbacks.final_mass_stage_parking_pass(feature)
    ]
    candidate_pool.sort(key=callbacks.design_review_quality_key, reverse=True)
    top_k = int(config.get("top_k") or 40)

    def review_stratum(feature: Feature) -> str:
        props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        signature = props.get("source_signature") if isinstance(props.get("source_signature"), dict) else {}
        rule = signature.get("rule_evidence") if isinstance(signature.get("rule_evidence"), dict) else {}
        descriptor = rule.get("research_diversity_descriptor") if isinstance(rule.get("research_diversity_descriptor"), dict) else {}
        family = str(
            callbacks.source_family(feature)
            or descriptor.get("mass_language")
            or signature.get("family")
            or props.get("operator_family")
            or "unknown"
        )
        height = float(props.get("height") or 0.0)
        return f"{family}|h={height:.2f}"

    # VLM input must represent the whole legal design population. A raw top-k
    # slice over-samples one currently fashionable family and later forces the
    # final guard to reinsert repeated VLM-scored forms. Select one best member
    # per language first, then round-robin deeper representatives.
    strata: dict[str, list[Feature]] = {}
    for feature in candidate_pool:
        strata.setdefault(review_stratum(feature), []).append(feature)
    candidates: list[Feature] = []
    depth = 0
    while len(candidates) < top_k:
        added = False
        for key in sorted(strata):
            bucket = strata[key]
            if depth < len(bucket):
                candidates.append(bucket[depth])
                added = True
                if len(candidates) >= top_k:
                    break
        if not added:
            break
        depth += 1
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    if scorer is None and config.get("require_vlm"):
        temp_dir = tempfile.TemporaryDirectory(prefix="maas-preference-vlm-")
        raw_cache_dir = str(config.get("cache_dir") or "").strip()
        cache_dir = None
        if raw_cache_dir:
            cache_dir = Path(raw_cache_dir).expanduser()
            if not cache_dir.is_absolute():
                cache_dir = _design_paths.workspace_root() / cache_dir
        scorer = openai_preview_preference_scorer(preview_dir=Path(temp_dir.name), cache_dir=cache_dir)
    if config.get("require_vlm") and scorer is None:
        raise ValueError("required MAAS preference VLM loop needs an image-backed scorer")
    try:
        references = load_reference_tree(preference_reference_root(config))
    except Exception:
        references = []
    scored_count = 0
    cache_hit_count = 0
    failed_count = 0
    proxy_count = 0
    model_name = config.get("model") or None

    def evaluate(feature: Feature) -> tuple[Feature, list[dict[str, Any]], dict[str, Any] | None, str]:
        matches = match_reference_context(feature, references, limit=5)
        if scorer is None:
            return feature, matches, None, ""
        try:
            return feature, matches, scorer(feature=feature, reference_matches=matches, model=model_name), ""
        except Exception as exc:
            return feature, matches, None, str(exc)

    def attach_result(
        feature: Feature,
        matches: list[dict[str, Any]],
        vlm_result: dict[str, Any] | None,
        vlm_error: str,
    ) -> None:
        props = feature.setdefault("properties", {})
        preference = build_preference_distillation(
            feature,
            image_uri=str(config.get("image_uri") or ""),
            vlm_model=(vlm_result or {}).get("model") if vlm_result else None,
            vlm_scores=(vlm_result or {}).get("concept_scores") if vlm_result else None,
            reference_matches=matches,
            vlm_status="scored" if vlm_result else ("failed" if vlm_error else "not_requested"),
            vlm_error=vlm_error,
        )
        preference["selection_stage"] = "pre_final_full_pool_top_k"
        if vlm_result and isinstance(vlm_result.get("critic_actions"), list):
            preference["critic_actions"] = list(vlm_result["critic_actions"])
        if vlm_result and isinstance(vlm_result.get("graph_edits"), list):
            preference["graph_edits"] = list(vlm_result["graph_edits"])
        props["preference_distillation"] = preference
        model = props.get("maas_model")
        if isinstance(model, dict):
            model["preference_distillation"] = preference

    try:
        if scorer is not None and len(candidates) > 1 and int(config.get("parallel_workers") or 1) > 1:
            worker_count = min(len(candidates), int(config.get("parallel_workers") or 1))
            results_by_id: dict[int, tuple[Feature, list[dict[str, Any]], dict[str, Any] | None, str]] = {}
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = {executor.submit(evaluate, feature): feature for feature in candidates}
                for future in as_completed(futures):
                    feature, matches, vlm_result, vlm_error = future.result()
                    results_by_id[id(feature)] = (feature, matches, vlm_result, vlm_error)
            for feature in candidates:
                _, matches, vlm_result, vlm_error = results_by_id[id(feature)]
                if vlm_error:
                    failed_count += 1
                    if config.get("require_vlm"):
                        raise ValueError(f"required MAAS preference VLM scoring failed: {vlm_error}")
                attach_result(feature, matches, vlm_result, vlm_error)
                if vlm_result:
                    scored_count += 1
                    cache_hit_count += int(bool(vlm_result.get("cache_hit")))
        else:
            for feature in candidates:
                feature, matches, vlm_result, vlm_error = evaluate(feature)
                if scorer is None:
                    proxy_count += 1
                if vlm_error:
                    failed_count += 1
                    if config.get("require_vlm"):
                        raise ValueError(f"required MAAS preference VLM scoring failed: {vlm_error}")
                attach_result(feature, matches, vlm_result, vlm_error)
                if vlm_result:
                    scored_count += 1
                    cache_hit_count += int(bool(vlm_result.get("cache_hit")))
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()
    features.sort(key=callbacks.design_review_quality_key, reverse=True)
    return {
        "schema_version": "arr.maas.preference_loop.v1",
        "enabled": True,
        "status": "scored" if scored_count else "proxy_scored",
        "require_vlm": bool(config.get("require_vlm")),
        "top_k": top_k,
        "candidate_pool_count": len(candidate_pool),
        "attempted_count": len(candidates),
        "vlm_scored_count": scored_count,
        "vlm_cache_hit_count": cache_hit_count,
        "vlm_cache_miss_count": max(0, scored_count - cache_hit_count),
        "proxy_count": proxy_count,
        "failed_count": failed_count,
        "reference_count": len(references),
        "parallel_workers": int(config.get("parallel_workers") or 1),
        "model": str(config.get("model") or ""),
    }


__all__ = [
    "PreferenceLoopCallbacks",
    "apply_preference_loop",
    "feature_preview_png",
    "openai_preview_preference_scorer",
    "preference_loop_config",
    "preference_score",
    "preference_vlm_scored",
]
