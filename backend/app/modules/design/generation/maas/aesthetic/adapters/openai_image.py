"""OpenAI GPT Image adapter for MAAS aesthetic image-to-image generation."""

from __future__ import annotations

import base64
from collections import Counter
import hashlib
import os
from pathlib import Path
from typing import Any

from PIL import Image

from backend.app.modules.design.generation.paths import aesthetic_media_root

from backend.app.modules.design.generation.maas.agents.elevation_agent.panel_roles import apply_roof_semantic_guard, is_mass_color, locked_sheet_panel_roles
from backend.app.modules.design.generation.maas.aesthetic.contracts import ProviderResult, RenderedReference


class OpenAIImageAdapter:
    name = "gpt-image"

    def __init__(self, *, output_dir: str | Path | None = None) -> None:
        self.output_dir = Path(output_dir or aesthetic_media_root() / "generated")

    def generate(self, job: dict[str, Any], reference: RenderedReference) -> ProviderResult:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return _not_configured("OPENAI_API_KEY is not set.")
        reference_path = Path(reference.uri)
        if not reference_path.exists():
            return _not_configured(f"Reference image does not exist: {reference.uri}")

        try:
            from openai import OpenAI
        except Exception as exc:  # pragma: no cover - depends on deployment env
            return _not_configured(f"openai package unavailable: {exc}")

        prompt = job.get("prompt", {}).get("prompt") or ""
        negative = job.get("prompt", {}).get("negative_prompt") or ""
        reference_type = reference.metadata.get("reference_type") if isinstance(reference.metadata, dict) else None
        if reference_type == "multi_view_pack":
            reference_instruction = (
                "The input is a locked multi-view architectural massing sheet with front, right, back, left, axon, and top views. "
                "Generate one coherent photorealistic architectural facade/material concept for the same building across all views. "
                "Treat the output as a projection-ready facade texture atlas for the existing 3D mass: material scale, window rhythm, mullions, balcony depth, reveals, parapets, and corner returns must align across panels. "
                "Keep facade rhythm, material palette, floor lines, openings, corners, roofline, and massing steps consistent between panels. "
                "Replace the diagrammatic orange mass panels with credible finished architecture in each view; keep only the panel layout and locked silhouette. "
            )
        elif reference_type == "locked_mass_sheet":
            reference_instruction = (
                "The input is a locked four-view architectural MASS sheet containing isometric, opposite, top, and front views of the same building. "
                "Generate one coherent photorealistic facade and material proposal across every panel. "
                "Keep the sheet layout, every camera, and every MASS outline exactly aligned so the result remains directly comparable to the source. "
            )
        elif reference_type == "locked_elevation_view":
            view = str(reference.metadata.get("view") or job.get("view") or "")
            reference_instruction = (
                f"The input is the locked orthographic {view} elevation of one immutable MASS. "
                f"Apply the shared facade strategy to this {view} view while keeping its camera, "
                "projection, silhouette, roofline, floor count, setbacks, voids, bridges, "
                "cantilevers, and proportions exactly registered to the source. "
            )
        else:
            reference_instruction = "Edit this legal massing reference into a photorealistic projection-ready architectural facade concept. "
        projection_instruction = (
            "Keep this orthographic view and do not change its camera or projection. "
            if reference_type == "locked_elevation_view"
            else (
                "The top panel must remain a roof/top view, the front panel must remain "
                "an orthographic front view, and no panel may change camera or projection. "
            )
        )
        full_prompt = (
            f"{reference_instruction}{prompt} "
            f"Use real architectural material detail, natural lighting, believable glazing, fine surface texture, and construction-scale facade proportions. "
            f"Keep openings, reveals, mullions, parapets, and corner returns strictly inside the existing colored MASS pixels. "
            f"Strictly preserve the exact silhouette, footprint, roofline, height, floor count, and mass steps. "
            f"{projection_instruction}"
            f"Do not add landscape, trees, roads, podiums, roofs, floors, or building pixels outside the supplied MASS silhouette. "
            f"Do not make a freestanding beauty render, collage, wallpaper texture, repeated sticker windows, or change the building mass; the image must remain usable as facade texture evidence for the locked MAAS geometry. "
            f"Negative constraints: {negative}"
        )
        model = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-2")
        size = os.getenv("OPENAI_IMAGE_SIZE", "1024x1024")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        output_path = self.output_dir / f"{_safe_id(job)}.openai.png"
        provider_reference_path = reference_path
        evidence = {
            "model": model,
            "size": size,
            "reference_asset_id": reference.asset_id,
            "prompt_sha256": hashlib.sha256(full_prompt.encode("utf-8")).hexdigest(),
            "input_image_sha256": hashlib.sha256(reference_path.read_bytes()).hexdigest(),
            "output_image_sha256": "",
            "request_id": "",
            "usage": {},
            "retry_count": 0,
            "edit_mask_sha256": "",
            "edit_mask_editable_ratio": 0.0,
            "provider_input_image_sha256": "",
            "post_composite_silhouette_lock": False,
            "post_composite_white_hole_repairs": 0,
            "roof_semantic_guard": {
                "status": "not_evaluated",
                "changed_pixel_count": 0,
            },
            "view": str(reference.metadata.get("view") or job.get("view") or ""),
            "outside_mask_changed_pixels": None,
        }
        mask_path = None
        if reference_type == "locked_mass_sheet":
            provider_reference_path = _prepare_locked_mass_sheet(
                reference_path,
                self.output_dir / f"{_safe_id(job)}.locked-input.png",
                size,
            )
            mask_path, editable_ratio = _write_locked_mass_mask(
                provider_reference_path,
                self.output_dir / f"{_safe_id(job)}.mask.png",
            )
            evidence["edit_mask_sha256"] = hashlib.sha256(
                mask_path.read_bytes()
            ).hexdigest()
            evidence["edit_mask_editable_ratio"] = round(editable_ratio, 6)
        elif reference_type == "locked_elevation_view":
            mask_path, editable_ratio = _write_locked_elevation_mask(
                provider_reference_path,
                self.output_dir / f"{_safe_id(job)}.{evidence['view']}.mask.png",
            )
            evidence["edit_mask_sha256"] = hashlib.sha256(
                mask_path.read_bytes()
            ).hexdigest()
            evidence["edit_mask_editable_ratio"] = round(editable_ratio, 6)
        evidence["provider_input_image_sha256"] = hashlib.sha256(
            provider_reference_path.read_bytes()
        ).hexdigest()

        try:
            client = OpenAI(api_key=api_key)
            with (
                provider_reference_path.open("rb") as image_file,
                mask_path.open("rb") if mask_path else _null_context() as mask_file,
            ):
                request = {
                    "model": model,
                    "image": image_file,
                    "prompt": full_prompt,
                    "size": size,
                    "n": 1,
                }
                if mask_file is not None:
                    request["mask"] = mask_file
                raw_api = getattr(client.images, "with_raw_response", None)
                if raw_api is not None:
                    raw_response = raw_api.edit(**request)
                    response = raw_response.parse()
                    headers = getattr(raw_response, "headers", {}) or {}
                    evidence["request_id"] = str(
                        headers.get("x-request-id")
                        or headers.get("request-id")
                        or ""
                    )
                else:  # pragma: no cover - compatibility with older SDKs
                    response = client.images.edit(**request)
            usage = getattr(response, "usage", None)
            if usage is not None:
                evidence["usage"] = _serializable_usage(usage)
            item = response.data[0]
            b64_json = getattr(item, "b64_json", None)
            url = getattr(item, "url", None)
            if b64_json:
                output_path.write_bytes(base64.b64decode(b64_json))
                if mask_path is not None:
                    repaired_pixels = _composite_locked_mass_output(
                        output_path,
                        provider_reference_path,
                        mask_path,
                    )
                    evidence["post_composite_silhouette_lock"] = True
                    evidence["post_composite_white_hole_repairs"] = repaired_pixels
                    evidence["outside_mask_changed_pixels"] = (
                        _outside_mask_change_count(
                            output_path,
                            provider_reference_path,
                            mask_path,
                        )
                    )
                    if reference_type == "locked_mass_sheet":
                        presentation = job.get("presentation")
                        presentation = (
                            presentation
                            if isinstance(presentation, dict)
                            else {}
                        )
                        panel_roles = presentation.get("panel_roles")
                        if not isinstance(panel_roles, list):
                            panel_roles = list(locked_sheet_panel_roles())
                        evidence["roof_semantic_guard"] = (
                            apply_roof_semantic_guard(
                                output_path,
                                provider_reference_path,
                                panel_roles,
                            )
                        )
                asset_uri = str(output_path)
                evidence["output_image_sha256"] = hashlib.sha256(
                    output_path.read_bytes()
                ).hexdigest()
            elif url:
                asset_uri = url
            else:
                return ProviderResult(
                    provider=self.name,
                    status="fail",
                    assets=[],
                    metadata=evidence,
                    issues=[{"code": "missing_image_payload", "message": "OpenAI response did not include b64_json or url."}],
                )
        except Exception as exc:  # pragma: no cover - network/provider behavior
            return ProviderResult(
                provider=self.name,
                status="fail",
                assets=[],
                metadata=evidence,
                issues=[{"code": "provider_error", "message": str(exc)}],
            )

        return ProviderResult(
            provider=self.name,
            status="complete",
            assets=[
                {
                    "asset_id": f"asset:maas-aesthetic-generated:{_safe_id(job)}:openai",
                    "uri": asset_uri,
                    "media_type": "image/png",
                    "source_bundle_id": job.get("source_bundle_id"),
                    "candidate_id": job.get("candidate_id"),
                    "legal_status_effect": "none",
                    "role": "generated_facade_image",
                }
            ],
            metadata=evidence,
        )


def _safe_id(job: dict[str, Any]) -> str:
    raw_attempt = job.get("attempt")
    attempt = raw_attempt if raw_attempt is not None else 0
    raw = ":".join((
        str(job.get("source_bundle_id") or "bundle"),
        str(job.get("candidate_id") or "candidate"),
        str(job.get("view") or "view"),
        f"attempt-{attempt}",
    ))
    return "".join(ch if ch.isalnum() else "_" for ch in raw)[-120:]


def _not_configured(message: str) -> ProviderResult:
    return ProviderResult(
        provider="gpt-image",
        status="not_configured",
        assets=[],
        metadata={},
        issues=[{"code": "provider_not_configured", "message": message}],
    )


def _serializable_usage(usage: Any) -> dict[str, Any]:
    if hasattr(usage, "model_dump"):
        value = usage.model_dump()
        return dict(value) if isinstance(value, dict) else {}
    if isinstance(usage, dict):
        return dict(usage)
    return {}


class _null_context:
    def __enter__(self):
        return None

    def __exit__(self, _exc_type, _exc, _traceback):
        return False


def _write_locked_mass_mask(
    reference_path: Path,
    output_path: Path,
) -> tuple[Path, float]:
    with Image.open(reference_path) as source:
        rgb = source.convert("RGB")
        mask = Image.new("RGBA", rgb.size, (255, 255, 255, 255))
        source_pixels = rgb.load()
        mask_pixels = mask.load()
        editable = 0
        total = max(1, rgb.width * rgb.height)
        for y in range(rgb.height):
            for x in range(rgb.width):
                if is_mass_color(source_pixels[x, y]):
                    mask_pixels[x, y] = (255, 255, 255, 0)
                    editable += 1
        if editable == 0:
            raise ValueError("locked MASS mask contains no editable geometry pixels")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        mask.save(output_path, format="PNG")
    return output_path, editable / total


def _write_locked_elevation_mask(
    reference_path: Path,
    output_path: Path,
) -> tuple[Path, float]:
    with Image.open(reference_path) as source:
        rgb = source.convert("RGB")
        border = [
            rgb.getpixel((x, y))
            for x, y in (
                *((x, 0) for x in range(rgb.width)),
                *((x, rgb.height - 1) for x in range(rgb.width)),
                *((0, y) for y in range(rgb.height)),
                *((rgb.width - 1, y) for y in range(rgb.height)),
            )
        ]
        background = Counter(border).most_common(1)[0][0]
        candidates = {
            (x, y)
            for y in range(rgb.height)
            for x in range(rgb.width)
            if max(
                abs(int(rgb.getpixel((x, y))[channel]) - int(background[channel]))
                for channel in range(3)
            ) > 12
        }
        silhouette: set[tuple[int, int]] = set()
        while candidates:
            seed = candidates.pop()
            component = {seed}
            stack = [seed]
            while stack:
                x, y = stack.pop()
                for adjacent in (
                    (x - 1, y),
                    (x + 1, y),
                    (x, y - 1),
                    (x, y + 1),
                ):
                    if adjacent in candidates:
                        candidates.remove(adjacent)
                        component.add(adjacent)
                        stack.append(adjacent)
            if len(component) > len(silhouette):
                silhouette = component
        if not silhouette:
            raise ValueError("locked elevation mask contains no editable geometry pixels")
        mask = Image.new("RGBA", rgb.size, (255, 255, 255, 255))
        pixels = mask.load()
        for x, y in silhouette:
            pixels[x, y] = (255, 255, 255, 0)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        mask.save(output_path, format="PNG")
    return output_path, len(silhouette) / max(1, rgb.width * rgb.height)


def _prepare_locked_mass_sheet(
    reference_path: Path,
    output_path: Path,
    requested_size: str,
) -> Path:
    try:
        width, height = (
            int(value)
            for value in str(requested_size).lower().split("x", 1)
        )
    except (TypeError, ValueError):
        width, height = 1024, 1024
    width = max(256, width)
    height = max(256, height)
    with Image.open(reference_path) as source:
        source = source.convert("RGBA")
        scale = min(width / source.width, height / source.height)
        resized = source.resize(
            (
                max(1, round(source.width * scale)),
                max(1, round(source.height * scale)),
            ),
            Image.Resampling.LANCZOS,
        )
        canvas = Image.new("RGBA", (width, height), (255, 255, 255, 255))
        origin = (
            (width - resized.width) // 2,
            (height - resized.height) // 2,
        )
        canvas.alpha_composite(resized, origin)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(output_path, format="PNG")
    return output_path


def _composite_locked_mass_output(
    generated_path: Path,
    locked_reference_path: Path,
    mask_path: Path,
) -> int:
    with (
        Image.open(generated_path) as generated,
        Image.open(locked_reference_path) as locked,
        Image.open(mask_path) as mask,
    ):
        generated_rgba = generated.convert("RGBA").resize(
            locked.size,
            Image.Resampling.LANCZOS,
        )
        locked_rgba = locked.convert("RGBA")
        preserve_mask = mask.getchannel("A")
        generated_pixels = generated_rgba.load()
        locked_pixels = locked_rgba.load()
        mask_pixels = preserve_mask.load()
        repaired_pixels = 0
        for y in range(locked.height):
            for x in range(locked.width):
                if mask_pixels[x, y] != 0:
                    continue
                red, green, blue, alpha = generated_pixels[x, y]
                if alpha < 16 or (red >= 246 and green >= 246 and blue >= 246):
                    generated_pixels[x, y] = locked_pixels[x, y]
                    repaired_pixels += 1
        composite = Image.composite(
            locked_rgba,
            generated_rgba,
            preserve_mask,
        )
        composite.save(generated_path, format="PNG")
    return repaired_pixels


def _outside_mask_change_count(
    generated_path: Path,
    locked_reference_path: Path,
    mask_path: Path,
) -> int:
    with (
        Image.open(generated_path) as generated,
        Image.open(locked_reference_path) as locked,
        Image.open(mask_path) as mask,
    ):
        generated_rgba = generated.convert("RGBA")
        locked_rgba = locked.convert("RGBA")
        preserve_mask = mask.getchannel("A")
        return sum(
            generated_rgba.getpixel((x, y)) != locked_rgba.getpixel((x, y))
            for y in range(locked_rgba.height)
            for x in range(locked_rgba.width)
            if preserve_mask.getpixel((x, y)) != 0
        )


__all__ = ["OpenAIImageAdapter"]
