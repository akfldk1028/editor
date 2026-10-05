"""Disk-level integrity audit for the architect-supplied BOOK corpus.

The typed contract and OCR manifest are useful only while they still point to
the exact 69 scans that were manually read. This module deliberately stays
outside generation and selection so corpus integrity cannot be confused with
candidate quality.
"""

from __future__ import annotations

from backend.app.modules.design.generation import paths as _design_paths

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any

from backend.app.modules.design.generation.maas.book_language.corpus_contract import BOOK_PAGE_COUNT
from backend.app.modules.design.generation.maas.book_language.registry import _OCR_PATH, build_book_language_registry


_PAGE_PATTERN = re.compile(r"^스캔_smallpdf_(\d+)\.jpg$", re.IGNORECASE)
_UNREFERENCED_SOURCE_PAGES = frozenset({1, 2, 4, 5, 13, 25, 38, 49, 59})


def default_book_scan_directory() -> Path:
    return _design_paths.workspace_root() / "docs" / "260506" / "BOOK"


def audit_book_corpus(
    scan_directory: Path | None = None,
    *,
    ocr_path: Path = _OCR_PATH,
) -> dict[str, Any]:
    """Compare typed pages, OCR provenance and the actual scan bytes."""

    scan_directory = Path(scan_directory or default_book_scan_directory()).resolve()
    ocr = json.loads(Path(ocr_path).read_text(encoding="utf-8"))
    registry = build_book_language_registry()
    issues: list[str] = []

    scans: dict[int, Path] = {}
    # The BOOK directory also contains the architect's comparison/reference
    # images. Only the immutable 69 scan naming contract belongs to the corpus.
    for path in scan_directory.glob("스캔_smallpdf_*.jpg"):
        match = _PAGE_PATTERN.fullmatch(path.name)
        if match is None:
            continue
        page = int(match.group(1))
        if page in scans:
            issues.append(f"duplicate_scan_page:{page}")
        scans[page] = path

    expected_pages = list(range(1, BOOK_PAGE_COUNT + 1))
    actual_pages = sorted(scans)
    if actual_pages != expected_pages:
        issues.append(f"scan_page_sequence:{actual_pages}")

    ocr_pages = list(ocr.get("pages") or ())
    ocr_page_numbers = [int(item.get("page", -1)) for item in ocr_pages]
    if int(ocr.get("page_count", -1)) != BOOK_PAGE_COUNT:
        issues.append(f"ocr_declared_page_count:{ocr.get('page_count')}")
    if ocr_page_numbers != expected_pages:
        issues.append(f"ocr_page_sequence:{ocr_page_numbers}")

    for record in ocr_pages:
        page = int(record.get("page", -1))
        scan = scans.get(page)
        if scan is None:
            continue
        digest = sha256(scan.read_bytes()).hexdigest()
        if str(record.get("sha256") or "") != digest:
            issues.append(f"sha256_mismatch:{page}")
        source_path = str(record.get("source_path") or "").replace("\\", "/")
        if not (source_path == scan.name or source_path.endswith(f"/{scan.name}")):
            issues.append(f"source_path_mismatch:{page}")
        if not isinstance(record.get("ocr_lines"), list):
            issues.append(f"ocr_lines_missing:{page}")

    registry_pages = list(registry.get("pages") or ())
    registry_page_numbers = [int(item.get("page", -1)) for item in registry_pages]
    if registry_page_numbers != expected_pages:
        issues.append(f"registry_page_sequence:{registry_page_numbers}")
    referenced_pages = {
        int(item["page"])
        for item in registry_pages
        if item.get("principle_ids")
    }
    if set(expected_pages) - referenced_pages != _UNREFERENCED_SOURCE_PAGES:
        issues.append("registry_page_reference_partition")

    principle_ids = [str(item.get("principle_id") or "") for item in registry.get("principles") or ()]
    duplicate_ids = sorted(
        principle_id for principle_id, count in Counter(principle_ids).items()
        if principle_id and count > 1
    )
    if duplicate_ids:
        issues.extend(f"duplicate_principle_id:{value}" for value in duplicate_ids)

    return {
        "schema_version": "arr.maas.book_corpus_audit.v1",
        "hard_pass": not issues,
        "issues": issues,
        "scan_directory": str(scan_directory),
        "scan_page_count": len(scans),
        "ocr_page_count": len(ocr_pages),
        "registry_page_count": len(registry_pages),
        "principle_count": len(principle_ids),
        "unreferenced_source_pages": sorted(_UNREFERENCED_SOURCE_PAGES),
        "page_section_counts": dict(Counter(item.get("section") for item in registry_pages)),
    }


__all__ = ["audit_book_corpus", "default_book_scan_directory"]
