"""Resolve persisted reference-image paths across ARR runtime environments."""

from __future__ import annotations

from backend.app.modules.design.generation import paths as _design_paths

from pathlib import Path, PurePosixPath
from urllib.parse import quote


def workspace_root() -> Path:
    """Return the 25_ACE repository root from this source module."""
    return _design_paths.workspace_root()


def _wsl_mount_path(value: str) -> Path | None:
    normalized = value.replace("\\", "/")
    if not normalized.lower().startswith("/mnt/"):
        return None
    parts = PurePosixPath(normalized).parts
    if len(parts) < 4 or len(parts[2]) != 1:
        return None
    return Path(f"{parts[2].upper()}:\\").joinpath(*parts[3:])


def _workspace_suffix_path(value: str, root: Path) -> Path | None:
    """Recover repo-relative paths persisted from a different cwd."""
    parts = [part for part in value.replace("\\", "/").split("/") if part not in {"", ".", ".."}]
    lowered = [part.lower() for part in parts]
    for anchor in ("docs", "arr", "scripts"):
        if anchor in lowered:
            index = lowered.index(anchor)
            return root.joinpath(*parts[index:])
    return None


def resolve_reference_image_path(value: str, *, root: Path | None = None) -> Path | None:
    """Resolve Windows, WSL and historical repo-relative image paths."""
    raw_value = str(value or "").strip()
    if not raw_value:
        return None
    repository = (root or workspace_root()).resolve()
    raw = Path(raw_value)
    candidates: list[Path] = []
    mounted = _wsl_mount_path(raw_value)
    if mounted is not None:
        candidates.append(mounted)
    if raw.is_absolute():
        candidates.append(raw)
    else:
        candidates.extend((Path.cwd() / raw, repository / raw))
    suffix = _workspace_suffix_path(raw_value, repository)
    if suffix is not None:
        candidates.append(suffix)

    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()
    return None


def reference_image_preview_url(value: str, *, root: Path | None = None) -> str:
    """Return the same-origin reference asset URL used by the design UI."""

    repository = (root or workspace_root()).resolve()
    path = resolve_reference_image_path(value, root=repository)
    if path is None:
        return ""
    corpus_root = (repository / "docs" / "ai-session-memory" / "reference-corpus").resolve()
    try:
        relative = path.relative_to(corpus_root)
    except ValueError:
        return ""
    return f"/design/maas/reference-assets/{quote(relative.as_posix(), safe='/')}"


__all__ = ["reference_image_preview_url", "resolve_reference_image_path", "workspace_root"]
