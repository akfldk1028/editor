"""Complete 134-entry BOOK language catalog extracted from the supplied CSV."""

from __future__ import annotations

from backend.app.modules.design.generation import paths as _design_paths

import csv
from functools import lru_cache
from pathlib import Path
import re
from typing import Any

from backend.app.modules.design.generation.maas.book_language.source_bundle import load_book_source_bundle


SCHEMA_VERSION = "arr.maas.book_language_catalog.v1"
EXPECTED_LAYER_COUNTS = {
    "process": 29,
    "diagram": 11,
    "operation": 30,
    "combination": 20,
    "aggregation": 5,
    "aggregation-expression": 9,
    "implementation": 30,
}


def catalog_path() -> Path:
    return (
        _design_paths.package_root("design/maas/book_language/data/source")
        / "BOOK_건축언어_전체목록.csv"
    )


def scan_pages(scan: str) -> tuple[int, ...]:
    pages: list[int] = []
    for token in str(scan or "").split(","):
        numbers = [int(value) for value in re.findall(r"\d+", token)]
        if not numbers:
            continue
        if len(numbers) == 1:
            pages.append(numbers[0])
        else:
            pages.extend(range(numbers[0], numbers[1] + 1))
    return tuple(dict.fromkeys(page for page in pages if 1 <= page <= 69))


@lru_cache(maxsize=1)
def load_book_language_catalog() -> dict[str, Any]:
    source_bundle = load_book_source_bundle()
    path = catalog_path()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        entries = [
            {
                **{key: str(value or "").strip() for key, value in row.items()},
                "catalog_id": f"book:catalog:{str(row.get('id') or '').strip()}",
                "scan_pages": list(scan_pages(str(row.get("scan") or ""))),
            }
            for row in csv.DictReader(handle)
        ]
    counts = {
        layer: sum(entry["layer"] == layer for entry in entries)
        for layer in EXPECTED_LAYER_COUNTS
    }
    if len(entries) != 134 or counts != EXPECTED_LAYER_COUNTS:
        raise ValueError(f"BOOK language catalog contract mismatch: {len(entries)} entries, {counts}")
    return {
        "schema_version": SCHEMA_VERSION,
        "source_path": str(path),
        "source_bundle_schema_version": source_bundle["schema_version"],
        "source_bundle_document_count": source_bundle["document_count"],
        "entry_count": len(entries),
        "layer_counts": counts,
        "entries": entries,
    }


__all__ = ["EXPECTED_LAYER_COUNTS", "SCHEMA_VERSION", "catalog_path", "load_book_language_catalog", "scan_pages"]
