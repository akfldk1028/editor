"""Candidate crop helpers for MAAS contact-sheet VLM scoring."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image


CROP_SCHEMA_VERSION = "arr.maas.candidate_crops.v1"

CARD_W = 410
CARD_H = 285
MARGIN_X = 32
MARGIN_Y = 112
GAP_X = 18
GAP_Y = 18
COLS = 5


def crop_candidate_images(
    *,
    sheet_path: Path,
    output_dir: Path,
    features: list[dict[str, Any]],
    overwrite: bool = True,
) -> dict[str, Any]:
    """Crop each MAAS card from a contact sheet into per-candidate PNGs."""
    if not sheet_path.exists():
        raise FileNotFoundError(f"MAAS contact sheet does not exist: {sheet_path}")
    output_dir.mkdir(parents=True, exist_ok=True)
    crop_index: dict[str, str] = {}
    with Image.open(sheet_path) as image:
        for index, feature in enumerate(features):
            candidate_id = _candidate_id(feature, index)
            crop_path = output_dir / f"{_safe_name(candidate_id)}.png"
            if overwrite or not crop_path.exists():
                image.crop(_card_box(index)).save(crop_path)
            crop_index[candidate_id] = str(crop_path)
    manifest = {
        "schema_version": CROP_SCHEMA_VERSION,
        "sheet_path": str(sheet_path),
        "output_dir": str(output_dir),
        "count": len(crop_index),
        "cards": crop_index,
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def crop_path_for_feature(crop_manifest: dict[str, Any], feature: dict[str, Any], index: int) -> Path | None:
    cards = crop_manifest.get("cards") if isinstance(crop_manifest.get("cards"), dict) else {}
    path = cards.get(_candidate_id(feature, index))
    return Path(path) if path else None


def _card_box(index: int) -> tuple[int, int, int, int]:
    col = index % COLS
    row = index // COLS
    x = MARGIN_X + col * (CARD_W + GAP_X)
    y = MARGIN_Y + row * (CARD_H + GAP_Y)
    return x, y, x + CARD_W, y + CARD_H


def _candidate_id(feature: dict[str, Any], index: int) -> str:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    return str(props.get("variant_id") or f"maas_{index + 1:02d}")


def _safe_name(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value.strip())
    return safe or "candidate"


__all__ = ["CROP_SCHEMA_VERSION", "crop_candidate_images", "crop_path_for_feature"]
