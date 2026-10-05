"""Fail-closed configuration for the optional design-memory Neo4j mirror."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from typing import Mapping


_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_LAW_DEFAULT_URI = "bolt://172.27.80.1:7687"
_LAW_DEFAULT_DATABASE = "neo4j"


def _value(environment: Mapping[str, str], name: str) -> str:
    return str(environment.get(name) or "").strip()


def _normalized_uri(value: str) -> str:
    return str(value or "").strip().rstrip("/").lower()


@dataclass(frozen=True)
class DesignMemorySettings:
    enabled: bool
    uri: str = ""
    user: str = ""
    password: str = field(default="", repr=False)
    database: str = ""
    reason: str = "not_enabled"
    missing_fields: tuple[str, ...] = ()

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> "DesignMemorySettings":
        values = os.environ if environment is None else environment
        requested = (
            _value(values, "MAAS_DESIGN_MEMORY_NEO4J_ENABLED").lower()
            in _TRUE_VALUES
        )
        if not requested:
            return cls(enabled=False, reason="not_enabled")

        design = {
            "uri": _value(values, "MAAS_DESIGN_MEMORY_NEO4J_URI"),
            "user": _value(values, "MAAS_DESIGN_MEMORY_NEO4J_USER"),
            "password": _value(
                values,
                "MAAS_DESIGN_MEMORY_NEO4J_PASSWORD",
            ),
            "database": _value(
                values,
                "MAAS_DESIGN_MEMORY_NEO4J_DATABASE",
            ),
        }
        missing = tuple(
            field_name
            for field_name, value in design.items()
            if not value
        )
        if missing:
            return cls(
                enabled=False,
                reason="incomplete_design_memory_settings",
                missing_fields=missing,
                **design,
            )

        law_uri = _value(values, "NEO4J_URI") or _LAW_DEFAULT_URI
        law_database = (
            _value(values, "NEO4J_DATABASE")
            or _LAW_DEFAULT_DATABASE
        )
        if (
            _normalized_uri(design["uri"]) == _normalized_uri(law_uri)
            and design["database"].casefold() == law_database.casefold()
        ):
            return cls(
                enabled=False,
                reason="law_database_collision",
                **design,
            )

        return cls(enabled=True, reason="enabled", **design)


__all__ = ["DesignMemorySettings"]
