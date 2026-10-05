"""Small atomic writers for one-MASS execution artifacts."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping
import uuid


def write_json_atomic(path: Path, payload: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


__all__ = ["write_json_atomic"]
