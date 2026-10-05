"""Deterministic PNG renderer for locked MAAS mass geometry."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from backend.app.modules.design.generation.maas.aesthetic.contracts import RenderedReference


class ReferencePngRenderer:
    """Render a simple white-mass reference PNG from GeoJSON.

    This is intentionally conservative. It is not a photoreal renderer; it is a
    stable geometry reference for image-to-image providers and silhouette checks.
    """

    def __init__(self, output_dir: str | Path, *, size: int = 1024) -> None:
        self.output_dir = Path(output_dir)
        self.size = size

    def render(self, job: dict[str, Any]) -> RenderedReference:
        locked = job.get("locked_geometry") or {}
        mass_geojson = locked.get("mass_geojson") or {}
        geometry = mass_geojson.get("geometry") or {}
        rings = _rings_from_geometry(geometry)
        if not rings:
            raise ValueError("Cannot render MAAS reference PNG without Polygon/MultiPolygon geometry.")

        digest = hashlib.sha256(
            json.dumps(
                {
                    "source_bundle_id": job.get("source_bundle_id"),
                    "candidate_id": job.get("candidate_id"),
                    "geometry": geometry,
                    "metrics": locked.get("geometry_metrics") or {},
                },
                sort_keys=True,
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest()[:16]
        asset_id = f"asset:maas-reference-render:{digest}"
        filename = f"{digest}.png"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        output_path = self.output_dir / filename

        image = Image.new("RGB", (self.size, self.size), "#f8fafc")
        draw = ImageDraw.Draw(image)
        bounds = _bounds(rings)
        projected = [[_project(point, bounds, self.size) for point in ring] for ring in rings]

        shadow_offset = max(10, self.size // 48)
        for ring in projected:
            draw.polygon([(x + shadow_offset, y + shadow_offset) for x, y in ring], fill="#cbd5e1")
        for index, ring in enumerate(projected):
            fill = "#ffffff" if index == 0 else "#e2e8f0"
            draw.polygon(ring, fill=fill, outline="#0f172a")
            draw.line(ring + [ring[0]], fill="#0f172a", width=max(3, self.size // 256))

        metrics = locked.get("geometry_metrics") or {}
        floors = metrics.get("num_floors")
        if isinstance(floors, int) and floors > 1:
            min_x = min(x for ring in projected for x, _ in ring)
            max_x = max(x for ring in projected for x, _ in ring)
            min_y = min(y for ring in projected for _, y in ring)
            max_y = max(y for ring in projected for _, y in ring)
            for i in range(1, min(floors, 18)):
                y = min_y + (max_y - min_y) * i / floors
                draw.line([(min_x, y), (max_x, y)], fill="#94a3b8", width=1)

        image.save(output_path)
        return RenderedReference(
            asset_id=asset_id,
            uri=str(output_path),
            media_type="image/png",
            metadata={
                "renderer": "ReferencePngRenderer",
                "source_bundle_id": job.get("source_bundle_id"),
                "candidate_id": job.get("candidate_id"),
                "width": self.size,
                "height": self.size,
                "sha256": _file_sha256(output_path),
                "geometry_lock": job.get("reference_render", {}).get("geometry_lock", {}),
            },
        )


def _rings_from_geometry(geometry: dict[str, Any]) -> list[list[list[float]]]:
    if geometry.get("type") == "Polygon":
        return [geometry.get("coordinates", [[]])[0]]
    if geometry.get("type") == "MultiPolygon":
        return [polygon[0] for polygon in geometry.get("coordinates", []) if polygon]
    return []


def _bounds(rings: list[list[list[float]]]) -> tuple[float, float, float, float]:
    xs = [point[0] for ring in rings for point in ring]
    ys = [point[1] for ring in rings for point in ring]
    return min(xs), min(ys), max(xs), max(ys)


def _project(point: list[float], bounds: tuple[float, float, float, float], size: int) -> tuple[float, float]:
    min_x, min_y, max_x, max_y = bounds
    pad = size * 0.16
    span_x = max(max_x - min_x, 1e-12)
    span_y = max(max_y - min_y, 1e-12)
    scale = min((size - pad * 2) / span_x, (size - pad * 2) / span_y)
    x = pad + (point[0] - min_x) * scale
    y = size - (pad + (point[1] - min_y) * scale)
    return x, y


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


__all__ = ["ReferencePngRenderer"]
