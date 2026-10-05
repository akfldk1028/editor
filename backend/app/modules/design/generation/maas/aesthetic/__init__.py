"""Aesthetic image-generation support for MAAS candidates.

This package keeps AI image generation downstream of legal massing. Image
models may propose facade/material treatments, but they must not replace the
MAAS mass geometry or legal evidence.
"""

from backend.app.modules.design.generation.maas.aesthetic.image_job import build_aesthetic_image_job
from backend.app.modules.design.generation.maas.aesthetic.pipeline import build_aesthetic_pipeline_result
from backend.app.modules.design.generation.maas.aesthetic.prompts import build_facade_prompt
from backend.app.modules.design.generation.maas.aesthetic.validators import validate_aesthetic_job

__all__ = [
    "build_aesthetic_image_job",
    "build_aesthetic_pipeline_result",
    "build_facade_prompt",
    "validate_aesthetic_job",
]
