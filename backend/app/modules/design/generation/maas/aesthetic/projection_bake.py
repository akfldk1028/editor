"""Deterministic texture bake assets for MAAS facade projection."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from backend.app.modules.design.generation.maas.aesthetic.contracts import ProviderResult
from backend.app.modules.design.generation.maas.aesthetic.projection_mesh import ATLAS_LAYOUT


def attach_baked_projection_assets(
    provider_result: ProviderResult,
    reference_metadata: dict[str, Any] | None = None,
    *,
    atlas_size: int = 1536,
) -> ProviderResult:
    """Compose facade panel assets into a texture atlas and bake manifest.

    The output is still deterministic and local. It does not invent geometry and
    does not mutate legal evidence. A future neural or GPU worker can replace
    this function while keeping the same asset roles.
    """

    projection_uri = (((reference_metadata or {}).get("condition_pack") or {}).get("projection_manifest") or {}).get("uri")
    if not isinstance(projection_uri, str):
        return provider_result
    projection_path = Path(projection_uri)
    if not projection_path.exists():
        return provider_result

    panel_assets = [
        asset for asset in provider_result.assets
        if asset.get("role") == "facade_panel_image"
        and isinstance(asset.get("uri"), str)
        and not str(asset.get("uri")).startswith(("http://", "https://"))
    ]
    panels_by_view = {
        str(asset.get("metadata", {}).get("view")): asset
        for asset in panel_assets
        if asset.get("metadata", {}).get("view")
    }
    required_views = ("front", "right", "back", "left")
    if not all(view in panels_by_view for view in required_views):
        return provider_result

    quality = _validate_projection_panels(panels_by_view)
    if quality["status"] != "pass":
        metadata = dict(provider_result.metadata or {})
        metadata["texture_bake"] = {
            "mode": "deterministic_panel_atlas_bake",
            "status": "skipped",
            "reason": quality["reason"],
            "metrics": quality["metrics"],
        }
        issues = list(provider_result.issues or [])
        issues.append({
            "code": "projection_panels_not_texture_ready",
            "message": quality["reason"],
            "metrics": quality["metrics"],
        })
        return ProviderResult(
            provider=provider_result.provider,
            status=provider_result.status,
            assets=list(provider_result.assets),
            metadata=metadata,
            issues=issues,
        )

    try:
        projection = json.loads(projection_path.read_text(encoding="utf-8"))
    except Exception:
        return provider_result

    source_asset_id = _source_asset_id(provider_result)
    out_dir = _output_dir(provider_result, projection_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    atlas_path = out_dir / "baked_texture_atlas.png"
    manifest_path = out_dir / "bake_manifest.json"

    atlas = Image.new("RGB", (atlas_size, atlas_size), "#f8fafc")
    for view, rect in ATLAS_LAYOUT.items():
        asset = panels_by_view.get(view)
        if not asset:
            continue
        panel_path = Path(str(asset["uri"]))
        if not panel_path.exists():
            continue
        with Image.open(panel_path).convert("RGB") as panel:
            x, y, w, h = _pixel_rect(rect, atlas_size)
            atlas.paste(panel.resize((w, h), Image.Resampling.LANCZOS), (x, y))

    _draw_surface_guides(atlas, projection.get("surfaces") or [])
    atlas.save(atlas_path)

    bake_manifest = {
        "schema_version": "arr.maas.texture_bake.v0",
        "mode": "deterministic_panel_atlas_bake",
        "source_projection_manifest": str(projection_path),
        "source_panel_asset_ids": {
            view: panels_by_view[view].get("asset_id")
            for view in panels_by_view
        },
        "texture_atlas": {
            "uri": str(atlas_path),
            "media_type": "image/png",
            "size_px": [atlas_size, atlas_size],
            "uv_space": "0_1_top_left",
        },
        "surface_count": len(projection.get("surfaces") or []),
        "surfaces": [
            {
                "id": surface.get("id"),
                "view": surface.get("view"),
                "plane_id": surface.get("plane_id"),
                "uv": surface.get("uv"),
                "triangles": surface.get("triangles"),
                "source_panel_view": surface.get("source_panel_view"),
            }
            for surface in projection.get("surfaces") or []
        ],
        "legal_status_effect": "none",
    }
    manifest_path.write_text(json.dumps(bake_manifest, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")

    assets = list(provider_result.assets)
    assets.extend([
        {
            "asset_id": f"{source_asset_id}:bake:atlas",
            "uri": str(atlas_path),
            "media_type": "image/png",
            "source_bundle_id": _first_asset_value(provider_result, "source_bundle_id"),
            "candidate_id": _first_asset_value(provider_result, "candidate_id"),
            "legal_status_effect": "none",
            "role": "baked_texture_atlas",
            "metadata": {
                "projection_manifest_uri": str(projection_path),
                "bake_manifest_uri": str(manifest_path),
                "mode": "deterministic_panel_atlas_bake",
            },
        },
        {
            "asset_id": f"{source_asset_id}:bake:manifest",
            "uri": str(manifest_path),
            "media_type": "application/json",
            "source_bundle_id": _first_asset_value(provider_result, "source_bundle_id"),
            "candidate_id": _first_asset_value(provider_result, "candidate_id"),
            "legal_status_effect": "none",
            "role": "texture_bake_manifest",
            "metadata": {
                "projection_manifest_uri": str(projection_path),
                "texture_atlas_uri": str(atlas_path),
                "mode": "deterministic_panel_atlas_bake",
            },
        },
    ])
    metadata = dict(provider_result.metadata or {})
    metadata["texture_bake"] = {
        "mode": "deterministic_panel_atlas_bake",
        "texture_atlas_asset_id": f"{source_asset_id}:bake:atlas",
        "bake_manifest_asset_id": f"{source_asset_id}:bake:manifest",
        "projection_manifest_uri": str(projection_path),
    }
    return ProviderResult(
        provider=provider_result.provider,
        status=provider_result.status,
        assets=assets,
        metadata=metadata,
        issues=list(provider_result.issues or []),
    )


def _pixel_rect(rect: list[float], atlas_size: int) -> tuple[int, int, int, int]:
    x, y, w, h = rect
    return (
        round(x * atlas_size),
        round(y * atlas_size),
        max(1, round(w * atlas_size)),
        max(1, round(h * atlas_size)),
    )


def _validate_projection_panels(panels_by_view: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Reject presentation-board panels before they become broken 3D textures.

    A projection-ready panel should contain mostly facade/roof material. If a
    provider returns an elevation sheet with white margins, labels, and empty
    background, baking it into glTF creates the floating white-card artifact.
    """

    metrics: dict[str, Any] = {}
    blocking_views: list[str] = []
    for view in ("front", "right", "back", "left"):
        asset = panels_by_view.get(view)
        path = Path(str(asset.get("uri"))) if asset else None
        if not path or not path.exists():
            blocking_views.append(view)
            metrics[view] = {"error": "missing_panel"}
            continue
        try:
            with Image.open(path).convert("RGB") as panel:
                pale_ratio = _pale_pixel_ratio(panel)
                top_pale_ratio = _pale_pixel_ratio(_crop_band(panel, "top", 0.08))
                top_sky_ratio = _sky_pixel_ratio(_crop_band(panel, "top", 0.12))
        except Exception as exc:
            blocking_views.append(view)
            metrics[view] = {"error": str(exc)}
            continue
        metrics[view] = {
            "pale_pixel_ratio": round(pale_ratio, 4),
            "top_pale_pixel_ratio": round(top_pale_ratio, 4),
            "top_sky_pixel_ratio": round(top_sky_ratio, 4),
        }
        if pale_ratio > 0.35 or top_pale_ratio > 0.22 or top_sky_ratio > 0.28:
            blocking_views.append(view)

    if blocking_views:
        return {
            "status": "fail",
            "reason": (
                "Generated facade panels are not projection-ready textures "
                "(labels, sky/background, or presentation-sheet margins detected), "
                "so glTF texture baking was skipped."
            ),
            "metrics": {"blocking_views": blocking_views, "views": metrics},
        }
    return {"status": "pass", "reason": "", "metrics": {"views": metrics}}


def _pale_pixel_ratio(image: Image.Image) -> float:
    total = max(1, image.width * image.height)
    pale = 0
    for red, green, blue in image.getdata():
        if red > 225 and green > 225 and blue > 225:
            pale += 1
    return pale / total


def _sky_pixel_ratio(image: Image.Image) -> float:
    total = max(1, image.width * image.height)
    sky = 0
    for red, green, blue in image.getdata():
        if blue > 120 and blue > red + 20 and blue > green + 5:
            sky += 1
    return sky / total


def _crop_band(image: Image.Image, edge: str, fraction: float) -> Image.Image:
    width, height = image.size
    band = max(1, int(height * fraction))
    if edge == "top":
        return image.crop((0, 0, width, band))
    if edge == "bottom":
        return image.crop((0, max(0, height - band), width, height))
    return image


def _draw_surface_guides(atlas: Image.Image, surfaces: list[dict[str, Any]]) -> None:
    draw = ImageDraw.Draw(atlas, "RGBA")
    width, height = atlas.size
    for surface in surfaces:
        uv = surface.get("uv")
        if not isinstance(uv, list) or len(uv) < 4:
            continue
        pts = [
            (float(point[0]) * width, float(point[1]) * height)
            for point in uv
            if isinstance(point, list) and len(point) >= 2
        ]
        if len(pts) != 4:
            continue
        draw.line(pts + [pts[0]], fill=(255, 255, 255, 76), width=2)


def _source_asset_id(provider_result: ProviderResult) -> str:
    for asset in provider_result.assets:
        if asset.get("role") == "generated_facade_image" and asset.get("asset_id"):
            return str(asset["asset_id"])
    return f"asset:maas-aesthetic-generated:{provider_result.provider}"


def _first_asset_value(provider_result: ProviderResult, key: str) -> Any:
    for asset in provider_result.assets:
        if asset.get(key) is not None:
            return asset.get(key)
    return None


def _output_dir(provider_result: ProviderResult, projection_path: Path) -> Path:
    for asset in provider_result.assets:
        if asset.get("role") == "generated_facade_image" and isinstance(asset.get("uri"), str):
            uri = str(asset["uri"])
            if not uri.startswith(("http://", "https://")):
                return Path(uri).with_suffix("")
    return projection_path.parent / "bake"


__all__ = ["attach_baked_projection_assets"]
