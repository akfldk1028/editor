"""Nano Banana / Gemini 2.5 Flash Image adapter."""

from __future__ import annotations

import base64
import json
import os
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from backend.app.modules.design.generation.maas.aesthetic.contracts import ProviderResult, RenderedReference


class NanoBananaAdapter:
    """Generate facade images with Google's Nano Banana image model.

    Official path:
    - `GEMINI_API_KEY` or `GOOGLE_API_KEY`
    - default model: `gemini-2.5-flash-image-preview`

    HTTP fallback:
    - `NANO_BANANA_ENDPOINT`
    - `NANO_BANANA_API_KEY`
    """

    name = "nano-banana"

    def __init__(self, *, output_dir: str | Path | None = None) -> None:
        self.output_dir = Path(output_dir or Path("media") / "maas" / "aesthetic" / "generated")

    def generate(self, job: dict[str, Any], reference: RenderedReference) -> ProviderResult:
        gemini_key = os.getenv("GEMINI_API_KEY")
        if gemini_key:
            google_key = os.environ.pop("GOOGLE_API_KEY", None)
            try:
                return self._generate_with_gemini(job, reference, gemini_key)
            finally:
                if google_key is not None:
                    os.environ["GOOGLE_API_KEY"] = google_key
        gemini_key = os.getenv("GOOGLE_API_KEY")
        if gemini_key:
            return self._generate_with_gemini(job, reference, gemini_key)
        return self._generate_with_http_fallback(job, reference)

    def _generate_with_gemini(self, job: dict[str, Any], reference: RenderedReference, api_key: str) -> ProviderResult:
        reference_path = Path(reference.uri)
        if not reference_path.exists():
            return _not_configured(f"Reference image does not exist: {reference.uri}")

        try:
            from google import genai
            from PIL import Image
        except Exception as exc:  # pragma: no cover - deployment env dependent
            return _not_configured(f"google-genai/Pillow unavailable: {exc}")

        self.output_dir.mkdir(parents=True, exist_ok=True)
        output_path = self.output_dir / f"{_safe_id(job)}.nano-banana.png"

        client = genai.Client(api_key=api_key)
        image = Image.open(reference_path)
        last_error: Exception | None = None
        for model in _candidate_models():
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=[_prompt(job, reference), image],
                )
                for part in response.candidates[0].content.parts:
                    inline_data = getattr(part, "inline_data", None)
                    if inline_data is not None and getattr(inline_data, "data", None):
                        generated = Image.open(BytesIO(inline_data.data))
                        generated.save(output_path)
                        return ProviderResult(
                            provider=self.name,
                            status="complete",
                            assets=[_asset(job, str(output_path), "nano-banana")],
                            metadata={
                                "api": "google-genai",
                                "model": model,
                                "reference_asset_id": reference.asset_id,
                            },
                        )
            except Exception as exc:  # pragma: no cover - provider/network behavior
                last_error = exc
                if "not found" in str(exc).lower() or "not supported" in str(exc).lower():
                    continue
                break
        if last_error is not None:
            return ProviderResult(
                provider=self.name,
                status="fail",
                assets=[],
                metadata={"api": "google-genai", "models": _candidate_models()},
                issues=[{"code": "provider_error", "message": str(last_error)}],
            )

        return ProviderResult(
            provider=self.name,
            status="fail",
            assets=[],
            metadata={"api": "google-genai", "models": _candidate_models()},
            issues=[{"code": "missing_image_payload", "message": "Gemini response did not include inline image data."}],
        )

    def _generate_with_http_fallback(self, job: dict[str, Any], reference: RenderedReference) -> ProviderResult:
        endpoint = os.getenv("NANO_BANANA_ENDPOINT")
        api_key = os.getenv("NANO_BANANA_API_KEY")
        if not endpoint or not api_key:
            return _not_configured(
                "Set GEMINI_API_KEY/GOOGLE_API_KEY for official Gemini API, or NANO_BANANA_ENDPOINT and NANO_BANANA_API_KEY for HTTP fallback."
            )

        reference_path = Path(reference.uri)
        if not reference_path.exists():
            return _not_configured(f"Reference image does not exist: {reference.uri}")

        payload = {
            "prompt": _prompt(job, reference),
            "negative_prompt": job.get("prompt", {}).get("negative_prompt") or "",
            "image_base64": base64.b64encode(reference_path.read_bytes()).decode("ascii"),
            "metadata": {
                "source_bundle_id": job.get("source_bundle_id"),
                "candidate_id": job.get("candidate_id"),
                "must_not_change": job.get("evidence_policy", {}).get("must_not_change", []),
            },
        }
        try:
            request = Request(
                endpoint,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urlopen(request, timeout=int(os.getenv("NANO_BANANA_TIMEOUT", "120"))) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:  # pragma: no cover
            return ProviderResult(
                provider=self.name,
                status="fail",
                assets=[],
                metadata={"api": "http-fallback", "endpoint": endpoint},
                issues=[{"code": "provider_error", "message": str(exc)}],
            )

        self.output_dir.mkdir(parents=True, exist_ok=True)
        asset_uri = data.get("image_url") or data.get("asset_url")
        if data.get("image_base64"):
            output_path = self.output_dir / f"{_safe_id(job)}.nano-banana.png"
            output_path.write_bytes(base64.b64decode(data["image_base64"]))
            asset_uri = str(output_path)
        if not asset_uri:
            return ProviderResult(
                provider=self.name,
                status="fail",
                assets=[],
                metadata={"api": "http-fallback", "endpoint": endpoint},
                issues=[{"code": "missing_image_payload", "message": "Nano Banana response did not include image output."}],
            )

        return ProviderResult(
            provider=self.name,
            status="complete",
            assets=[_asset(job, asset_uri, "nano-banana")],
            metadata={"api": "http-fallback", "endpoint": endpoint, "reference_asset_id": reference.asset_id},
        )


def _prompt(job: dict[str, Any], reference: RenderedReference) -> str:
    prompt = job.get("prompt", {}).get("prompt") or ""
    negative = job.get("prompt", {}).get("negative_prompt") or ""
    reference_type = reference.metadata.get("reference_type") if isinstance(reference.metadata, dict) else None
    if reference_type == "multi_view_pack":
        reference_instruction = (
            "Use the input image as a locked multi-view architectural massing sheet with front, right, back, left, axon, and top views. "
            "Create one coherent photorealistic facade/material concept for the same building across all views, but do not create an architectural presentation board. "
            "Treat the output as projection-ready facade surface imagery for the existing 3D mass: material scale, window rhythm, mullions, balcony depth, reveals, parapets, and corner returns must align across panels. "
            "Each view cell must be filled edge-to-edge by usable building surface content, with no white margins, no sheet borders, no view labels, no captions, and no empty background inside the cell. "
            "Keep facade rhythm, material palette, floor lines, openings, corners, roofline, and massing steps consistent between panels. "
            "Replace the diagrammatic orange mass panels with credible finished architecture in each view; keep only the locked silhouette and facade direction logic. "
        )
    else:
        reference_instruction = "Use the input image as a locked architectural massing reference for photorealistic facade projection. "
    return (
        f"{prompt}\n\n"
        f"{reference_instruction}"
        "Only redesign facade materials, window rhythm, surface detail, lighting, and presentation style. "
        "Use real architectural material detail, natural lighting, believable glazing, fine surface texture, and construction-scale facade proportions. "
        "Design a refined facade composition with base-middle-top hierarchy, aligned floor datums, deep window reveals, corner-return continuity, parapet coping, and a clear entrance zone. "
        "The output must look like realistic facade material applied to a building, not like an elevation drawing, illustrated sheet, diagram, or presentation layout. "
        "Do not make a freestanding beauty render or change the building mass; the image must remain usable as facade texture evidence for the locked MAAS geometry. "
        "Do not create a collage, flat wallpaper texture, repeated sticker windows, or a diagrammatic orange mass render. "
        "Do not include panel names, labels, borders, white background, page margins, annotation lines, or drawing-sheet framing. "
        "Do not change the silhouette, footprint, height, floor count, massing steps, setbacks, or roofline.\n"
        f"Negative constraints: {negative}"
    )


def _asset(job: dict[str, Any], uri: str, suffix: str) -> dict[str, Any]:
    return {
        "asset_id": f"asset:maas-aesthetic-generated:{_safe_id(job)}:{suffix}",
        "uri": uri,
        "media_type": "image/png",
        "source_bundle_id": job.get("source_bundle_id"),
        "candidate_id": job.get("candidate_id"),
        "legal_status_effect": "none",
        "role": "generated_facade_image",
    }


def _not_configured(message: str) -> ProviderResult:
    return ProviderResult(
        provider="nano-banana",
        status="not_configured",
        assets=[],
        metadata={},
        issues=[{"code": "provider_not_configured", "message": message}],
    )


def _safe_id(job: dict[str, Any]) -> str:
    raw = f"{job.get('source_bundle_id') or 'bundle'}:{job.get('candidate_id') or 'candidate'}"
    return "".join(ch if ch.isalnum() else "_" for ch in raw)[-120:]


def _candidate_models() -> list[str]:
    configured = os.getenv("NANO_BANANA_MODEL")
    defaults = [
        "nano-banana-pro-preview",
        "gemini-2.5-flash-image",
        "gemini-3.1-flash-image",
        "gemini-3-pro-image",
    ]
    models = [configured] if configured else []
    for model in defaults:
        if model not in models:
            models.append(model)
    return [model for model in models if model]


__all__ = ["NanoBananaAdapter"]
