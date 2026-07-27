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
    index_json_path: Path | None = None
    index_html_path: Path | None = None
    termination_reason: str | None = None
    evaluation_count: int = 0
    accepted: bool = False
    error: str | None = None
