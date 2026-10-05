"""Content-addressed BOOK composition paths offered to the LLM architect."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
import json
from typing import Any, Iterator

from backend.app.modules.design.generation.maas.grammar.vocab import SUPPORTED_VERBS

from backend.app.modules.design.generation.maas.book_language.corpus_contract import AGGREGATION_CONTRACTS, BASE_OPERATIVES, BASE_VOLUME_FRACTIONS, BOOK_ORIENTATIONS, BOOK_VARIATION_COUNT, CASE_STUDY_CONTRACTS, COMBINATION_CONTRACTS


SCHEMA_VERSION = "arr.maas.book_composition_path.v1"
LATTICE_SCHEMA_VERSION = "arr.maas.book_composition_lattice.v1"


@dataclass(frozen=True)
class _PrinciplePath:
    principle_id: str
    kind: str
    page: int
    base_operative_id: str
    ordered_operations: tuple[str, ...]
    transformation: str
    cardinality: str


@dataclass(frozen=True)
class BookCompositionPath:
    base_volume_label: str
    base_volume_fraction: float
    orientation: str
    variation_index: int
    principle_id: str
    principle_kind: str
    page: int
    base_operative_id: str
    ordered_operations: tuple[str, ...]
    graph_edges: tuple[tuple[str, str, str], ...]
    topology_class: str
    executable: bool
    incompatibility_reasons: tuple[str, ...] = ()

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "base_volume_label": self.base_volume_label,
            "base_volume_fraction": self.base_volume_fraction,
            "orientation": self.orientation,
            "variation_index": self.variation_index,
            "principle_id": self.principle_id,
            "principle_kind": self.principle_kind,
            "page": self.page,
            "base_operative_id": self.base_operative_id,
            "ordered_operations": list(self.ordered_operations),
            "graph_edges": [list(edge) for edge in self.graph_edges],
            "topology_class": self.topology_class,
        }

    @property
    def path_id(self) -> str:
        payload = json.dumps(
            self._identity_payload(),
            sort_keys=True,
            separators=(",", ":"),
        )
        return "book:path:" + sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._identity_payload(),
            "path_id": self.path_id,
            "executable": self.executable,
            "incompatibility_reasons": list(self.incompatibility_reasons),
            "matrix4_contract": {
                "schema_version": "arr.maas.book_basevolume_matrix4.v1",
                "count": 1,
                "coordinate_frame": "unitbox",
                "placement": "after_base_volume_before_ordered_operations",
                "authorship": "llm_typed_ast",
            },
            "parameter_state": {
                "book_variation_index": self.variation_index,
                "book_variation_count": BOOK_VARIATION_COUNT,
                "completion_authority": "llm_typed_ast",
            },
        }


def _principle_paths() -> tuple[_PrinciplePath, ...]:
    base_by_verb = {item.verb: item for item in BASE_OPERATIVES}
    records: list[_PrinciplePath] = []
    for item in BASE_OPERATIVES:
        records.append(_PrinciplePath(
            principle_id=item.principle_id,
            kind="base_operative",
            page=item.page,
            base_operative_id=item.principle_id,
            ordered_operations=(item.verb,),
            transformation=item.transformation,
            cardinality=item.cardinality,
        ))
    for index, item in enumerate(COMBINATION_CONTRACTS, start=1):
        base = base_by_verb[item.first]
        records.append(_PrinciplePath(
            principle_id=(
                f"book:combination:{index:02d}:{item.first}+{item.second}"
            ),
            kind="combination",
            page=item.page,
            base_operative_id=base.principle_id,
            ordered_operations=(item.first, item.second),
            transformation=base.transformation,
            cardinality=base.cardinality,
        ))
    for item in AGGREGATION_CONTRACTS:
        base = base_by_verb[item.operative]
        records.append(_PrinciplePath(
            principle_id=(
                f"book:aggregation:{'+'.join(item.methods)}:{item.operative}"
            ),
            kind="aggregation",
            page=item.page,
            base_operative_id=base.principle_id,
            ordered_operations=item.execution_verbs,
            transformation=base.transformation,
            cardinality=base.cardinality,
        ))
    for item in CASE_STUDY_CONTRACTS:
        base = base_by_verb[item.verbs[0]]
        records.append(_PrinciplePath(
            principle_id=f"book:case:{item.page}:{'+'.join(item.verbs)}",
            kind="case_study",
            page=item.page,
            base_operative_id=base.principle_id,
            ordered_operations=item.verbs,
            transformation=base.transformation,
            cardinality=base.cardinality,
        ))
    return tuple(records)


def iter_book_composition_paths() -> Iterator[BookCompositionPath]:
    """Yield the complete source-faithful lattice without form/site materialization."""

    for label, fraction in BASE_VOLUME_FRACTIONS:
        base_volume_id = f"book:base-volume:{label.replace('/', '-')}"
        for orientation in BOOK_ORIENTATIONS:
            orientation_id = f"book:orientation:{orientation}"
            for principle in _principle_paths():
                unsupported = tuple(
                    operation
                    for operation in principle.ordered_operations
                    if operation not in SUPPORTED_VERBS
                )
                edges = [
                    (base_volume_id, "oriented_as", orientation_id),
                    (orientation_id, "feeds", principle.base_operative_id),
                ]
                if principle.principle_id != principle.base_operative_id:
                    edges.append((
                        principle.base_operative_id,
                        "composes_to",
                        principle.principle_id,
                    ))
                for variation_index in range(BOOK_VARIATION_COUNT):
                    yield BookCompositionPath(
                        base_volume_label=label,
                        base_volume_fraction=float(fraction),
                        orientation=orientation,
                        variation_index=variation_index,
                        principle_id=principle.principle_id,
                        principle_kind=principle.kind,
                        page=principle.page,
                        base_operative_id=principle.base_operative_id,
                        ordered_operations=principle.ordered_operations,
                        graph_edges=tuple(edges),
                        topology_class=(
                            f"{principle.kind}:"
                            f"{principle.transformation}:"
                            f"{principle.cardinality}"
                        ),
                        executable=not unsupported,
                        incompatibility_reasons=tuple(
                            f"unsupported_operation:{item}"
                            for item in unsupported
                        ),
                    )


@lru_cache(maxsize=1)
def _paths_by_id() -> dict[str, BookCompositionPath]:
    return {
        item.path_id: item
        for item in iter_book_composition_paths()
    }


def book_composition_path_by_id(path_id: str) -> BookCompositionPath | None:
    return _paths_by_id().get(str(path_id or "").strip())


@lru_cache(maxsize=1)
def book_composition_lattice_summary() -> dict[str, Any]:
    paths = tuple(iter_book_composition_paths())
    ids = {item.path_id for item in paths}
    return {
        "schema_version": LATTICE_SCHEMA_VERSION,
        "path_count": len(paths),
        "unique_path_count": len(ids),
        "executable_path_count": sum(item.executable for item in paths),
        "base_volume_count": len(BASE_VOLUME_FRACTIONS),
        "orientation_count": len(BOOK_ORIENTATIONS),
        "variation_count": BOOK_VARIATION_COUNT,
        "principle_count": len(_principle_paths()),
        "principle_kind_counts": {
            kind: sum(item.kind == kind for item in _principle_paths())
            for kind in (
                "base_operative", "combination", "aggregation", "case_study",
            )
        },
    }


__all__ = [
    "BookCompositionPath",
    "LATTICE_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "book_composition_lattice_summary",
    "book_composition_path_by_id",
    "iter_book_composition_paths",
]
