from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class VisualReviewArtifacts:
    svg_path: Path
    png_path: Path
    html_path: Path
    report_path: Path
    needs_iteration: bool
    checks: dict[str, str]
