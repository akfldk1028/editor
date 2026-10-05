"""Editor-owned code and data locations for the design generation runtime."""
from __future__ import annotations

import os
from pathlib import Path


def editor_root() -> Path:
    return Path(__file__).resolve().parents[5]


def data_root() -> Path:
    configured = os.environ.get("EDITOR_DESIGN_DATA_DIR", "").strip()
    return Path(configured).expanduser().resolve() if configured else editor_root() / "runtime/editor/design"


def workspace_root() -> Path:
    return data_root()


def backend_root() -> Path:
    return data_root() / "runtime"


def arr_root() -> Path:
    return data_root()


def book_scan_root() -> Path:
    """The 69 BOOK scans (docs/260506/BOOK); the OCR registry names them by file."""
    return workspace_root() / "docs" / "260506" / "BOOK"


def aesthetic_media_root() -> Path:
    """Reference and generated aesthetic images, under the data root's runtime media."""
    return backend_root() / "media" / "maas" / "aesthetic"


def package_root(source_package: str) -> Path:
    roots = {
        "design": Path(__file__).resolve().parent,
        "land": editor_root() / "backend/app/modules/land/reference",
        "law": editor_root() / "backend/app/modules/law/reference",
        "graph_db": editor_root() / "backend/app/adapters/design_storage",
    }
    owner, _, suffix = source_package.partition("/")
    if owner not in roots:
        raise ValueError(f"Unrecognized design resource owner: {owner}")
    return roots[owner] / suffix
