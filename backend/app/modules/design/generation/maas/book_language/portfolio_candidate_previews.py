"""Candidate-bound PNG assets for the MASS evaluation portfolio."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Callable, Iterable

from backend.app.modules.design.generation.maas.program_massing.benchmark import render_archive_sheet


_UNCERTIFIED_AUTHORED_VISUAL_PREFIX = (
    "authored profiled visual mesh requires certified nonempty projection:"
)


def render_candidate_preview_assets(
    candidates: Iterable[tuple[str, dict[str, Any]]],
    *,
    output_dir: Path,
    program_slug: str,
    renderer: Callable[..., None] = render_archive_sheet,
    exclusion_sink: list[dict[str, str]] | None = None,
) -> dict[str, str]:
    """Render certified candidates and report fail-closed visual exclusions."""

    root = Path(output_dir).resolve()
    preview_dir = root / "candidate-renders"
    preview_dir.mkdir(parents=True, exist_ok=True)
    safe_program = re.sub(
        r"[^A-Za-z0-9_.-]+", "-", str(program_slug)
    ).strip("-") or "program"
    paths: dict[str, str] = {}
    for index, (identity, feature) in enumerate(candidates, start=1):
        key = str(identity or "").strip()
        if not key or key in paths or not isinstance(feature, dict):
            continue
        suffix = re.sub(r"[^A-Za-z0-9]+", "", key)[:16] or f"{index:03d}"
        path = preview_dir / f"{safe_program}-{index:03d}-{suffix}.png"
        try:
            renderer(
                [feature],
                path,
                title=f"MASS {index:03d} · {safe_program} · {key[:16]}",
            )
        except ValueError as exc:
            if not str(exc).startswith(_UNCERTIFIED_AUTHORED_VISUAL_PREFIX):
                raise
            if exclusion_sink is not None:
                exclusion_sink.append({
                    "program_hash": key,
                    "reason": "uncertified_authored_visual_projection",
                })
            continue
        if path.is_file():
            paths[key] = path.relative_to(root).as_posix()
    return paths


__all__ = ["render_candidate_preview_assets"]
