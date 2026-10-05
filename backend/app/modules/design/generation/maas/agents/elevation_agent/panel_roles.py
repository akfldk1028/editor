"""Panel semantics for the locked four-view architectural render sheet."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Mapping

from PIL import Image, ImageFilter


PanelRole = dict[str, object]


def locked_sheet_panel_roles() -> tuple[PanelRole, ...]:
    """Return normalized layout roles for the stable compiler MASS sheet."""

    return (
        {
            "role": "isometric",
            "bounds": [0.0, 0.0, 0.5, 0.5],
            "surface": "facade_and_roof",
        },
        {
            "role": "opposite",
            "bounds": [0.5, 0.0, 1.0, 0.5],
            "surface": "facade_and_roof",
        },
        {
            "role": "top",
            "bounds": [0.0, 0.5, 0.5, 1.0],
            "surface": "roof_only",
        },
        {
            "role": "front",
            "bounds": [0.5, 0.5, 1.0, 1.0],
            "surface": "facade",
        },
    )


def roof_mass_mask(
    reference_path: str | Path,
    panel_roles: Iterable[Mapping[str, object]],
) -> Image.Image:
    """Select only colored MASS pixels inside the panel marked ``top``."""

    top = next(
        (row for row in panel_roles if row.get("role") == "top"),
        None,
    )
    if top is None:
        raise ValueError("locked sheet panel roles require a top panel")
    bounds = top.get("bounds")
    if not isinstance(bounds, (list, tuple)) or len(bounds) != 4:
        raise ValueError("top panel requires four normalized bounds")
    with Image.open(Path(reference_path)) as source:
        rgb = source.convert("RGB")
        mask = Image.new("L", rgb.size, 0)
        source_pixels = rgb.load()
        mask_pixels = mask.load()
        left = max(0, min(rgb.width, round(float(bounds[0]) * rgb.width)))
        top_y = max(0, min(rgb.height, round(float(bounds[1]) * rgb.height)))
        right = max(left, min(rgb.width, round(float(bounds[2]) * rgb.width)))
        bottom = max(top_y, min(rgb.height, round(float(bounds[3]) * rgb.height)))
        for y in range(top_y, bottom):
            for x in range(left, right):
                if is_mass_color(source_pixels[x, y]):
                    mask_pixels[x, y] = 255
    return mask


def apply_roof_semantic_guard(
    generated_path: str | Path,
    locked_reference_path: str | Path,
    panel_roles: Iterable[Mapping[str, object]],
) -> dict[str, object]:
    """Suppress facade-like high-frequency grids only in the top MASS region."""

    generated_path = Path(generated_path)
    roles = tuple(panel_roles)
    roof_mask = roof_mass_mask(locked_reference_path, roles)
    if roof_mask.getbbox() is None:
        return {
            "schema_version": "arr.maas.roof_semantic_guard.v1",
            "status": "no_roof_mass",
            "changed_pixel_count": 0,
            "before_grid_score": 0.0,
            "after_grid_score": 0.0,
        }
    with Image.open(generated_path) as source:
        original = source.convert("RGB")
        before_score = _grid_score(original, roof_mask)
        radius = max(1.0, min(original.size) * 0.004)
        low_frequency = original.filter(ImageFilter.GaussianBlur(radius=radius))
        guarded = Image.composite(low_frequency, original, roof_mask)
        after_score = _grid_score(guarded, roof_mask)
        original_pixels = original.load()
        guarded_pixels = guarded.load()
        mask_pixels = roof_mask.load()
        changed = sum(
            1
            for y in range(original.height)
            for x in range(original.width)
            if mask_pixels[x, y]
            and original_pixels[x, y] != guarded_pixels[x, y]
        )
        guarded.save(generated_path, format="PNG")
    return {
        "schema_version": "arr.maas.roof_semantic_guard.v1",
        "status": "applied" if after_score < before_score else "needs_review",
        "changed_pixel_count": changed,
        "before_grid_score": round(before_score, 6),
        "after_grid_score": round(after_score, 6),
        "roof_mask_pixel_count": sum(1 for value in roof_mask.getdata() if value),
        "blur_radius": round(radius, 4),
    }


def is_mass_color(pixel: tuple[int, int, int]) -> bool:
    """Match the compiler's warm MASS fill without selecting white panels."""

    red, green, blue = pixel
    return (
        red >= 60
        and red >= green * 1.12
        and green >= blue * 1.18
        and red - blue >= 35
    )


def _grid_score(image: Image.Image, mask: Image.Image) -> float:
    pixels = image.convert("RGB").load()
    mask_pixels = mask.load()
    differences = 0.0
    pairs = 0
    for y in range(image.height):
        for x in range(image.width):
            if not mask_pixels[x, y]:
                continue
            current = pixels[x, y]
            for neighbor_x, neighbor_y in ((x + 1, y), (x, y + 1)):
                if (
                    neighbor_x >= image.width
                    or neighbor_y >= image.height
                    or not mask_pixels[neighbor_x, neighbor_y]
                ):
                    continue
                neighbor = pixels[neighbor_x, neighbor_y]
                differences += sum(
                    abs(int(left) - int(right))
                    for left, right in zip(current, neighbor)
                ) / (255.0 * 3.0)
                pairs += 1
    return differences / max(1, pairs)


__all__ = [
    "PanelRole",
    "apply_roof_semantic_guard",
    "is_mass_color",
    "locked_sheet_panel_roles",
    "roof_mass_mask",
]
