"""Extract page headings from the architect-supplied 69-page BOOK scan.

This is an evidence extraction utility, not a geometry generator. It keeps the
source page, checksum, OCR text and confidence so every later typed mutation can
be traced back to the supplied book instead of a prompt assertion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import cv2
import easyocr
import numpy as np


SCHEMA_VERSION = "arr.maas.book_ocr.v1"
BOOK_SCAN_GLOB = "스캔_smallpdf_*.jpg"


def extract_book_headings(book_dir: Path, *, crop_height: int = 420) -> dict[str, Any]:
    reader = easyocr.Reader(["en"], gpu=False, download_enabled=False, verbose=False)
    pages: list[dict[str, Any]] = []
    for path in sorted(book_dir.glob(BOOK_SCAN_GLOB), key=_page_number):
        raw = path.read_bytes()
        image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise RuntimeError(f"unable to decode {path}")
        oriented = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
        heading_band = oriented[: min(crop_height, oriented.shape[0]), :, :]
        detections = reader.readtext(heading_band, detail=1, paragraph=False)
        lines = [
            {
                "text": str(text).strip(),
                "confidence": round(float(confidence), 4),
                "box": [[round(float(x), 1), round(float(y), 1)] for x, y in box],
            }
            for box, text, confidence in detections
            if str(text).strip()
        ]
        pages.append({
            "page": _page_number(path),
            "source_path": path.as_posix(),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "orientation": "rotate_90_clockwise",
            "heading_crop_height": crop_height,
            "ocr_lines": lines,
        })
        print(f"BOOK OCR {pages[-1]['page']:02d}/69: {[line['text'] for line in lines[:6]]}", flush=True)
    return {
        "schema_version": SCHEMA_VERSION,
        "source": "architect_supplied_book_scan",
        "page_count": len(pages),
        "pages": pages,
    }


def _page_number(path: Path) -> int:
    match = re.search(r"_(\d+)\.jpg$", path.name, re.IGNORECASE)
    return int(match.group(1)) if match else 10_000


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("book_dir", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--crop-height", type=int, default=420)
    args = parser.parse_args()
    result = extract_book_headings(args.book_dir, crop_height=max(180, args.crop_height))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"WROTE {args.output} ({result['page_count']} pages)")


if __name__ == "__main__":
    main()
