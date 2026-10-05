"""Opt-in timing trace for the synchronous MAAS generation pipeline."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class GenerationTrace:
    enabled: bool
    started: float = field(default_factory=time.perf_counter)

    @classmethod
    def from_environment(cls) -> "GenerationTrace":
        enabled = os.getenv("MAAS_PROFILE_GENERATION", "").strip().lower() in {"1", "true", "yes", "on"}
        return cls(enabled=enabled)

    def checkpoint(self, stage: str, **values: Any) -> None:
        if not self.enabled:
            return
        print(
            "MAAS_PROFILE",
            stage,
            f"elapsed_ms={round((time.perf_counter() - self.started) * 1000)}",
            *(f"{key}={value}" for key, value in values.items()),
            flush=True,
        )


__all__ = ["GenerationTrace"]
