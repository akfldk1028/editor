"""Authoritative four-document bundle extracted from the supplied BOOK scans.

The CSV is the addressable vocabulary index.  The three Markdown documents
retain page structure, normalized terminology and page-level interpretation.
They are complementary evidence, so consumers must not silently replace the
bundle with a hand-written subset of verbs.
"""

from __future__ import annotations

from backend.app.modules.design.generation import paths as _design_paths

from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "arr.maas.book_source_bundle.v1"
SOURCE_SPECS = (
    (
        "catalog",
        "BOOK_건축언어_전체목록.csv",
        "complete 134-entry addressable language catalog",
    ),
    (
        "full_extraction",
        "BOOK_건축언어_전체추출.md",
        "page-faithful extracted headings, labels and relationships",
    ),
    (
        "term_index",
        "BOOK_건축용어_단어목록.md",
        "normalized architectural term inventory",
    ),
    (
        "page_index",
        "BOOK_페이지별_건축용어_정리.md",
        "page-by-page term, meaning and evidence index",
    ),
)


def source_root() -> Path:
    return _design_paths.package_root("design/maas/book_language/data/source")


@lru_cache(maxsize=1)
def load_book_source_bundle() -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    issues: list[str] = []
    for role, filename, purpose in SOURCE_SPECS:
        path = source_root() / filename
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8-sig")
        except OSError:
            issues.append(f"missing_source:{filename}")
            continue
        except UnicodeDecodeError:
            issues.append(f"invalid_utf8:{filename}")
            continue
        lines = text.splitlines()
        if not lines:
            issues.append(f"empty_source:{filename}")
        records.append({
            "role": role,
            "filename": filename,
            "path": str(path),
            "purpose": purpose,
            "line_count": len(lines),
            "byte_count": len(raw),
            "sha256": sha256(raw).hexdigest(),
        })

    if len(records) != len(SOURCE_SPECS):
        issues.append(f"source_count:{len(records)}")
    if issues:
        raise ValueError("BOOK source bundle contract mismatch: " + ", ".join(issues))
    return {
        "schema_version": SCHEMA_VERSION,
        "authority": "all four supplied BOOK extraction documents",
        "document_count": len(records),
        "documents": records,
    }


__all__ = [
    "SCHEMA_VERSION",
    "SOURCE_SPECS",
    "load_book_source_bundle",
    "source_root",
]
