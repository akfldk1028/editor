"""Immutable, selection-independent evidence for legal MASS candidates."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any


LegalMassArchiveRecord = dict[str, Any]


def _final_surface_payload_hash(payload: list[dict[str, Any]]) -> str:
    records = tuple(
        json.dumps(
            surface,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        for surface in payload
    )
    encoded = f"[{','.join(sorted(records))}]".encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class LegalMassArchive:
    """Keep the first legal record for each exact final geometry hash."""

    schema_version = "arr.maas.legal_mass_archive.v1"
    evidence_record_limit = 128

    def __init__(self) -> None:
        self._records_by_geometry_hash: dict[str, LegalMassArchiveRecord] = {}

    def admit(self, candidate: dict[str, Any]) -> LegalMassArchiveRecord | None:
        """Copy a certified legal candidate into the archive, if eligible."""

        policy_evidence = candidate.get("policy_evidence")
        if not isinstance(policy_evidence, dict) or not all(
            policy_evidence.get(key) is True
            for key in (
                "compiler_clean",
                "contained",
                "authored_surface_certified",
                "legal_hard_pass",
            )
        ):
            return None
        geometry_hash = str(candidate.get("geometry_hash") or "")
        program_hash = str(candidate.get("program_hash") or "")
        surface_payload = candidate.get("final_authored_surface_payload")
        surface_payload_hash = str(
            candidate.get("final_surface_payload_hash") or ""
        )
        if not (
            geometry_hash
            and program_hash
            and isinstance(surface_payload, list)
            and surface_payload
            and all(isinstance(surface, dict) for surface in surface_payload)
            and surface_payload_hash
        ):
            return None
        try:
            actual_surface_payload_hash = _final_surface_payload_hash(
                surface_payload
            )
        except (TypeError, ValueError):
            return None
        if actual_surface_payload_hash != surface_payload_hash:
            return None
        if geometry_hash in self._records_by_geometry_hash:
            return deepcopy(self._records_by_geometry_hash[geometry_hash])
        record: LegalMassArchiveRecord = {
            "schema_version": self.schema_version,
            "geometry_hash": geometry_hash,
            "program_hash": program_hash,
            "final_authored_surface_payload": deepcopy(surface_payload),
            "final_surface_payload_hash": surface_payload_hash,
            "normalized_source_surface_payload_hash": str(
                candidate.get("normalized_source_surface_payload_hash") or ""
            ),
            "surface_coordinate_frame": str(
                candidate.get("surface_coordinate_frame") or ""
            ),
            "policy_evidence": deepcopy(policy_evidence),
            "capacity_evidence": deepcopy(candidate.get("capacity_evidence") or {}),
            "scope": deepcopy(candidate.get("scope") or {}),
            "family": str(candidate.get("family") or ""),
            "lineage": deepcopy(candidate.get("lineage") or {}),
        }
        self._records_by_geometry_hash[geometry_hash] = record
        return deepcopy(record)

    def evidence(self, *, record_limit: int | None = None) -> dict[str, Any]:
        """Return bounded, detached run evidence without affecting selection."""

        limit = self.evidence_record_limit if record_limit is None else max(0, int(record_limit))
        records = list(self._records_by_geometry_hash.values())
        return {
            "schema_version": self.schema_version,
            "selection_effect": "none_archive_only",
            "record_count": len(records),
            "records": deepcopy(records[:limit]),
            "records_truncated": len(records) > limit,
        }
