from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class VisualReviewArtifacts:
    svg_path: Path
    png_path: Path
    html_path: Path
    report_path: Path
    artifact_links: dict[str, str]
    needs_iteration: bool
    checks: dict[str, str]


@dataclass(frozen=True)
class VisualReviewLoopResult:
    iterations_run: int
    final_needs_iteration: bool
    artifacts: list[VisualReviewArtifacts]
