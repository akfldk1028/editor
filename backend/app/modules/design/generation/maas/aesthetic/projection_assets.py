"""Projection-oriented assets for MAAS aesthetic provider outputs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image


PANEL_LAYOUT = {
    "front": (19, 19, 486, 739),
    "right": (524, 19, 486, 739),
    "back": (1029, 19, 486, 739),
    "left": (19, 777, 486, 739),
    "axon": (524, 777, 486, 739),
    "top": (1029, 777, 486, 739),
}


def attach_facade_panel_assets(provider_result: Any, reference_metadata: dict[str, Any] | None = None) -> Any:
    """Add cropped per-view panel assets to a provider result.

    Image providers currently return a single multi-view sheet. The Cesium
    renderer needs facade-addressable panels, so this helper derives stable
    `front/right/back/left` image assets without changing legal geometry.
    Remote provider URLs are left unchanged because they cannot be cropped
    locally in the Django process.
    """

    assets = list(getattr(provider_result, "assets", []) or [])
    generated = next((asset for asset in assets if asset.get("role") == "generated_facade_image"), None)
    if not generated:
        return provider_result
    uri = generated.get("uri")
    if not isinstance(uri, str) or uri.startswith(("http://", "https://")):
        return provider_result
    source_path = Path(uri)
    if not source_path.exists():
        return provider_result

    panel_assets = _crop_panels(
        source_path,
        source_asset_id=generated.get("asset_id") or "asset:maas-aesthetic-generated",
        source_bundle_id=generated.get("source_bundle_id"),
        candidate_id=generated.get("candidate_id"),
    )
    if not panel_assets:
        return provider_result

    metadata = dict(getattr(provider_result, "metadata", {}) or {})
    metadata["facade_projection"] = {
        "mode": "cropped_multiview_panels",
        "source_asset_id": generated.get("asset_id"),
        "panel_asset_ids": [asset["asset_id"] for asset in panel_assets],
        "reference_pack_id": ((reference_metadata or {}).get("condition_pack") or {}).get("pack_id"),
    }
    return type(provider_result)(
        provider=provider_result.provider,
        status=provider_result.status,
        assets=assets + panel_assets,
        metadata=metadata,
        issues=list(getattr(provider_result, "issues", []) or []),
    )


def _crop_panels(
    source_path: Path,
    *,
    source_asset_id: str,
    source_bundle_id: str | None,
    candidate_id: str | int | None,
) -> list[dict[str, Any]]:
    try:
        image = Image.open(source_path).convert("RGB")
    except Exception:
        return []

    width, height = image.size
    if width < 256 or height < 256:
        return []

    out_dir = source_path.with_suffix("")
    out_dir.mkdir(parents=True, exist_ok=True)
    scale_x = width / 1536
    scale_y = height / 1536
    panel_assets: list[dict[str, Any]] = []
    for view, (x, y, w, h) in PANEL_LAYOUT.items():
        left = round(x * scale_x)
        upper = round(y * scale_y)
        right = round((x + w) * scale_x)
        lower = round((y + h) * scale_y)
        if right <= left or lower <= upper:
            continue
        panel = image.crop((left, upper, right, lower))
        path = out_dir / f"{view}.panel.png"
        panel.save(path)
        panel_assets.append({
            "asset_id": f"{source_asset_id}:panel:{view}",
            "uri": str(path),
            "media_type": "image/png",
            "source_bundle_id": source_bundle_id,
            "candidate_id": candidate_id,
            "legal_status_effect": "none",
            "role": "facade_panel_image",
            "metadata": {
                "view": view,
                "source_asset_id": source_asset_id,
                "crop_space": "multiview_sheet_1536_normalized",
                "crop_box_1536": [x, y, w, h],
            },
        })
    return panel_assets


__all__ = ["attach_facade_panel_assets"]
