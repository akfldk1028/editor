"""Reference render specifications for MAAS aesthetic image jobs.

This module does not render pixels yet. It creates deterministic render specs so
future Playwright/Blender/OpenSCAD/Cesium renderers can produce reproducible
reference images for image-to-image generation.
"""

from __future__ import annotations

from typing import Any


DEFAULT_VIEWS = ("front", "front_left", "front_right", "aerial")


def build_reference_render_spec(evidence: dict[str, Any], *, views: tuple[str, ...] = DEFAULT_VIEWS) -> dict[str, Any]:
    candidate = evidence.get("candidate") or {}
    geometry = evidence.get("geometry") or {}
    metrics = geometry.get("geometry_metrics") or {}
    return {
        "type": "maas_reference_render_spec",
        "source_bundle_id": evidence.get("bundle_id"),
        "candidate_id": candidate.get("candidate_id"),
        "mass_shape": candidate.get("mass_shape"),
        "views": [
            {
                "view": view,
                "camera": _camera_for_view(view),
                "render_mode": "white_mass_with_edge_lines",
                "lock_silhouette": True,
            }
            for view in views
        ],
        "geometry_lock": {
            "height_m": metrics.get("height_m"),
            "num_floors": metrics.get("num_floors"),
            "shape_signature_3d": metrics.get("shape_signature_3d") or {},
            "mass_geojson_ref": "geometry.mass_geojson",
            "floor_plates_ref": "geometry.floor_plates",
            "mass_volumes_ref": "geometry.mass_volumes",
        },
    }


def _camera_for_view(view: str) -> dict[str, Any]:
    presets = {
        "front": {"azimuth_deg": 0, "elevation_deg": 12, "fov_deg": 45},
        "front_left": {"azimuth_deg": -35, "elevation_deg": 15, "fov_deg": 45},
        "front_right": {"azimuth_deg": 35, "elevation_deg": 15, "fov_deg": 45},
        "aerial": {"azimuth_deg": 35, "elevation_deg": 55, "fov_deg": 50},
    }
    return presets.get(view, {"azimuth_deg": 0, "elevation_deg": 15, "fov_deg": 45})


__all__ = ["DEFAULT_VIEWS", "build_reference_render_spec"]

