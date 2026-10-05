"""Deterministic cheap-first breadth scheduling for competition portfolios.

The scheduler deliberately owns no exact CSG operation.  It orders the
UnitBox/BaseVolume/BOOK supply, performs inexpensive typed and two-dimensional
screens, and returns a quota-protected shortlist for the existing exact legal,
parking, and hash gates.
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping, Sequence

from backend.app.modules.design.generation.maas.book_language.competition_portfolio_contract import BASE_SCOPES, CompetitionPortfolioContract, competition_portfolio_contract


CHEAP_EVALUATION_LIMIT = 192
EXACT_SHORTLIST_MINIMUM = 48
EXACT_SHORTLIST_MAXIMUM = 64
EXACT_HARD_PASS_MINIMUM = 24
EXACT_HARD_PASS_MAXIMUM = 28
QUOTA_AXES = (
    "body_family",
    "roof_family",
    "chassis_family",
    "plan_family",
    "book_principle_id",
)
STAGE_FAILURE_NAMES = (
    "book_bind",
    "authored_compile",
    "legal_section_screen",
    "affine_screen",
    "exact_csg",
    "capacity",
    "parking",
    "hash_bridge",
)


def _value(record: Any, name: str, default: Any = "") -> Any:
    if isinstance(record, Mapping):
        return record.get(name, default)
    return getattr(record, name, default)


def _record_key(record: Any, fallback_index: int = 0) -> str:
    value = _value(record, "key", "")
    return str(value or f"breadth-record-{fallback_index:06d}")


@dataclass(frozen=True)
class BreadthCoordinate:
    base_scope: str
    genotype_family: str = ""
    book_principle_kind: str = ""
    body_family: str = ""
    roof_family: str = ""
    capacity_band: str = ""


@dataclass(frozen=True)
class BreadthDeficit:
    """One typed cell shortage at a specific breadth stage."""

    axis: str
    cell: str
    required_count: int
    available_count: int
    stage: str = "cheap_screen"
    page_index: int = 0

    @property
    def shortfall(self) -> int:
        return max(0, int(self.required_count) - int(self.available_count))

    def to_dict(self) -> dict[str, Any]:
        return {
            "axis": self.axis,
            "cell": self.cell,
            "required_count": int(self.required_count),
            "available_count": int(self.available_count),
            "shortfall": self.shortfall,
            "stage": self.stage,
            "page_index": int(self.page_index),
        }


@dataclass(frozen=True)
class CheapScreenRecord:
    record: Any
    key: str
    page_index: int
    coordinate: BreadthCoordinate
    cheap_hard_pass: bool
    exact_required: bool
    failure_stage: str
    approximate_capacity_ratio: float
    score: float


@dataclass(frozen=True)
class BreadthScheduleResult:
    cheap_screen_records: tuple[CheapScreenRecord, ...]
    exact_shortlist: tuple[Any, ...]
    deficits: tuple[BreadthDeficit, ...]
    stage_failure_counts: Mapping[str, int]
    page_index: int
    next_page_index: int | None

    @property
    def feasible_supply(self) -> bool:
        return not self.deficits

    def evidence(self) -> dict[str, Any]:
        return {
            "schema_version": "arr.maas.competition_breadth_schedule.v1",
            "page_index": int(self.page_index),
            "next_page_index": self.next_page_index,
            "cheap_screen_count": len(self.cheap_screen_records),
            "cheap_hard_pass_count": sum(
                record.cheap_hard_pass
                for record in self.cheap_screen_records
            ),
            "exact_required_count": sum(
                record.exact_required
                for record in self.cheap_screen_records
            ),
            "exact_shortlist_count": len(self.exact_shortlist),
            "exact_required_shortlist_count": sum(
                bool(_value(record, "exact_required", False))
                for record in self.exact_shortlist
            ),
            "proved_cheap_shortlist_count": sum(
                not bool(_value(record, "exact_required", False))
                for record in self.exact_shortlist
            ),
            "exact_shortlist_bounds": {
                "minimum": EXACT_SHORTLIST_MINIMUM,
                "maximum": EXACT_SHORTLIST_MAXIMUM,
            },
            "stage_failure_counts": dict(self.stage_failure_counts),
            "deficits": [deficit.to_dict() for deficit in self.deficits],
            "feasible_supply": self.feasible_supply,
        }


def _coordinate(record: Any) -> BreadthCoordinate:
    return BreadthCoordinate(
        base_scope=str(_value(record, "base_scope", "unclassified")),
        genotype_family=str(
            _value(record, "genotype_family", "unclassified")
        ),
        book_principle_kind=str(
            _value(record, "book_principle_kind", "unclassified")
        ),
        body_family=str(_value(record, "body_family", "unclassified")),
        roof_family=str(_value(record, "roof_family", "unclassified")),
        capacity_band=str(
            _value(record, "capacity_band", "unclassified")
        ),
    )


def _compiled_cache_key(record: Any, fallback_index: int) -> str:
    typed_ast = _value(record, "typed_ast", None)
    if typed_ast is not None:
        program_hash = getattr(typed_ast, "program_hash", None)
        if callable(program_hash):
            try:
                return f"program:{program_hash()}"
            except (TypeError, ValueError):
                pass
        return f"typed-ast:{id(typed_ast)}"
    return f"record:{_record_key(record, fallback_index)}"


def _valid_exact_required_ast(record: Any) -> bool:
    if (
        _value(record, "exact_required", False) is not True
        or str(_value(record, "cheap_bounds_status", ""))
        != "unknown_bounds"
    ):
        return False
    typed_ast = _value(record, "typed_ast", None)
    validate = getattr(typed_ast, "validate", None)
    if typed_ast is None or not callable(validate):
        return False
    try:
        issues = tuple(validate())
    except (AttributeError, TypeError, ValueError):
        return False
    return not any(
        str(getattr(issue, "severity", "error")) == "error"
        for issue in issues
    )


def _sections_are_contained(
    floor_sections: Sequence[Any],
    legal_sections: Sequence[Any],
) -> bool:
    if len(floor_sections) != len(legal_sections):
        return False
    for section, legal_section in zip(floor_sections, legal_sections):
        if section is None or legal_section is None:
            return False
        try:
            if not (
                section.within(legal_section)
                or legal_section.covers(section)
            ):
                return False
        except (AttributeError, TypeError, ValueError):
            return False
    return True


def cheap_screen_records(
    records: Iterable[Any],
    *,
    legal_sections: Sequence[Any] = (),
    compile_typed_ast: Callable[[Any], Any] | None = None,
    legal_section_screen: Callable[[Any, Sequence[Any]], bool] | None = None,
    approximate_capacity: Callable[[Any], float | bool] | None = None,
) -> tuple[CheapScreenRecord, ...]:
    """Screen records without invoking exact legal CSG, parking, or hashing.

    A supplied typed-AST compiler is memoized by AST identity/program hash so
    the same authored program is compiled at most once during the cheap page.
    """

    screened: list[CheapScreenRecord] = []
    compilation_cache: dict[str, bool] = {}
    for index, record in enumerate(records):
        failure_stage = ""
        exact_required = False
        capacity_ratio = float(
            _value(record, "approximate_capacity_ratio", 1.0) or 0.0
        )
        if _value(record, "book_bind_pass", True) is not True:
            failure_stage = "book_bind"

        if not failure_stage:
            compile_pass = _value(record, "authored_compile_pass", True) is True
            if compile_typed_ast is not None:
                cache_key = _compiled_cache_key(record, index)
                if cache_key not in compilation_cache:
                    try:
                        compiled = compile_typed_ast(record)
                        compilation_cache[cache_key] = bool(
                            getattr(compiled, "status", "compiled")
                            == "compiled"
                            if compiled is not None
                            else False
                        )
                    except (TypeError, ValueError, RuntimeError):
                        compilation_cache[cache_key] = False
                compile_pass = compilation_cache[cache_key]
            if not compile_pass:
                if (
                    compile_typed_ast is None
                    and _valid_exact_required_ast(record)
                ):
                    failure_stage = "exact_required"
                    exact_required = True
                else:
                    failure_stage = "authored_compile"

        if not failure_stage:
            legal_pass = (
                _value(record, "legal_section_screen_pass", True) is True
            )
            if legal_section_screen is not None:
                try:
                    legal_pass = bool(
                        legal_section_screen(record, legal_sections)
                    )
                except (TypeError, ValueError):
                    legal_pass = False
            elif legal_sections:
                floor_sections = tuple(
                    _value(record, "floor_sections", ()) or ()
                )
                legal_pass = _sections_are_contained(
                    floor_sections,
                    legal_sections,
                )
            if not legal_pass:
                failure_stage = "legal_section_screen"

        if (
            not failure_stage
            and _value(record, "affine_screen_pass", True) is not True
        ):
            failure_stage = "affine_screen"

        if not failure_stage:
            capacity_pass = (
                _value(record, "approximate_capacity_pass", True) is True
            )
            if approximate_capacity is not None:
                try:
                    capacity_result = approximate_capacity(record)
                    if isinstance(capacity_result, bool):
                        capacity_pass = capacity_result
                    else:
                        capacity_ratio = float(capacity_result)
                        required_ratio = float(
                            _value(
                                record,
                                "required_capacity_ratio",
                                1.0,
                            )
                            or 1.0
                        )
                        capacity_pass = capacity_ratio + 1e-9 >= required_ratio
                except (TypeError, ValueError):
                    capacity_pass = False
            if not capacity_pass:
                failure_stage = "capacity"

        screened.append(CheapScreenRecord(
            record=record,
            key=_record_key(record, index),
            page_index=int(_value(record, "page_index", 0) or 0),
            coordinate=_coordinate(record),
            cheap_hard_pass=not failure_stage,
            exact_required=exact_required,
            failure_stage=failure_stage,
            approximate_capacity_ratio=capacity_ratio,
            score=float(_value(record, "score", 0.0) or 0.0),
        ))
    return tuple(screened)


def _balanced_records(
    records: Sequence[CheapScreenRecord],
) -> list[CheapScreenRecord]:
    """Round-robin full behavior cells, with the six scopes as outer cycle."""

    buckets: dict[
        tuple[str, str, str, str, str, str],
        deque[CheapScreenRecord],
    ] = defaultdict(deque)
    for record in records:
        coordinate = record.coordinate
        buckets[(
            coordinate.base_scope,
            coordinate.genotype_family,
            coordinate.book_principle_kind,
            coordinate.body_family,
            coordinate.roof_family,
            coordinate.capacity_band,
        )].append(record)
    scope_rank = {scope: index for index, scope in enumerate(BASE_SCOPES)}
    scope_keys: dict[
        str,
        deque[tuple[str, str, str, str, str, str]],
    ] = defaultdict(deque)
    for key in sorted(
        buckets,
        key=lambda value: (
            scope_rank.get(value[0], len(scope_rank)),
            value[1:],
        ),
    ):
        scope_keys[key[0]].append(key)
    scopes = sorted(
        scope_keys,
        key=lambda scope: (
            scope_rank.get(scope, len(scope_rank)),
            scope,
        ),
    )
    ordered: list[CheapScreenRecord] = []
    while scopes:
        next_scopes = []
        for scope in scopes:
            keys = scope_keys[scope]
            key = keys.popleft()
            bucket = buckets[key]
            ordered.append(bucket.popleft())
            if bucket:
                keys.append(key)
            if keys:
                next_scopes.append(scope)
        scopes = next_scopes
    return ordered


class CompetitionBreadthScheduler:
    """State-light scheduler for deterministic page-by-page replenishment."""

    def __init__(
        self,
        *,
        target_count: int = 20,
        contract: CompetitionPortfolioContract | None = None,
        cheap_evaluation_limit: int = CHEAP_EVALUATION_LIMIT,
        exact_shortlist_minimum: int = EXACT_SHORTLIST_MINIMUM,
        exact_shortlist_maximum: int = EXACT_SHORTLIST_MAXIMUM,
    ) -> None:
        self.target_count = int(target_count)
        self.contract = contract or competition_portfolio_contract(
            self.target_count
        )
        self.cheap_evaluation_limit = max(
            EXACT_SHORTLIST_MAXIMUM,
            int(cheap_evaluation_limit),
        )
        self.exact_shortlist_minimum = max(
            1,
            min(EXACT_SHORTLIST_MAXIMUM, int(exact_shortlist_minimum)),
        )
        self.exact_shortlist_maximum = max(
            self.exact_shortlist_minimum,
            min(EXACT_SHORTLIST_MAXIMUM, int(exact_shortlist_maximum)),
        )

    @property
    def base_scopes(self) -> tuple[str, ...]:
        return tuple(self.contract.base_scopes or BASE_SCOPES)

    def first_breadth_cycle(self) -> tuple[BreadthCoordinate, ...]:
        """Expose the scope-first deterministic cycle used by enumeration."""

        return tuple(
            BreadthCoordinate(base_scope=scope)
            for scope in self.base_scopes
        )

    def _required_cells(
        self,
        passed: Sequence[CheapScreenRecord],
        supplied: Mapping[str, Mapping[str, int]] | None,
    ) -> dict[str, dict[str, int]]:
        required: dict[str, dict[str, int]] = {
            axis: {
                str(_value(record.record, axis, "unclassified")): 1
                for record in passed
            }
            for axis in QUOTA_AXES
        }
        if self.contract.base_scope_minimum_each:
            required["base_scope"] = {
                scope: int(self.contract.base_scope_minimum_each)
                for scope in self.base_scopes
            }
        if self.contract.capacity_band_exact_counts:
            required["capacity_band"] = {
                str(cell): int(count)
                for cell, count
                in self.contract.capacity_band_exact_counts.items()
            }
        for axis, cells in (supplied or {}).items():
            required[str(axis)] = {
                str(cell): max(0, int(count))
                for cell, count in cells.items()
            }
        return required

    @staticmethod
    def _cell_count(
        records: Sequence[CheapScreenRecord],
        axis: str,
        cell: str,
    ) -> int:
        return sum(
            str(_value(record.record, axis, "unclassified")) == cell
            for record in records
        )

    def schedule_page(
        self,
        records: Iterable[Any],
        *,
        page_index: int,
        required_cells: Mapping[str, Mapping[str, int]] | None = None,
        legal_sections: Sequence[Any] = (),
        compile_typed_ast: Callable[[Any], Any] | None = None,
        legal_section_screen: (
            Callable[[Any, Sequence[Any]], bool] | None
        ) = None,
        approximate_capacity: Callable[[Any], float | bool] | None = None,
        downstream_stage_failure_counts: Mapping[str, int] | None = None,
    ) -> BreadthScheduleResult:
        screened = cheap_screen_records(
            tuple(records)[:self.cheap_evaluation_limit],
            legal_sections=legal_sections,
            compile_typed_ast=compile_typed_ast,
            legal_section_screen=legal_section_screen,
            approximate_capacity=approximate_capacity,
        )
        stage_counts = Counter(
            record.failure_stage
            for record in screened
            if record.failure_stage
        )
        for stage, count in (downstream_stage_failure_counts or {}).items():
            if stage not in STAGE_FAILURE_NAMES:
                raise ValueError(f"unknown breadth failure stage: {stage}")
            stage_counts[stage] += max(0, int(count))
        passed = _balanced_records([
            record for record in screened
            if record.cheap_hard_pass
        ])
        exact_required = _balanced_records([
            record for record in screened
            if record.exact_required
        ])
        eligible = _balanced_records([*passed, *exact_required])
        required = self._required_cells(eligible, required_cells)

        selected: list[CheapScreenRecord] = []
        selected_keys: set[str] = set()

        def admit(record: CheapScreenRecord) -> None:
            if (
                len(selected) >= self.exact_shortlist_maximum
                or record.key in selected_keys
            ):
                return
            selected.append(record)
            selected_keys.add(record.key)

        # Protect every required cell before score fill.  Rarest supply is
        # handled first, and one record may satisfy anchors on several axes.
        cell_requests = sorted(
            (
                (
                    self._cell_count(eligible, axis, cell),
                    axis,
                    cell,
                    required_count,
                )
                for axis, cells in required.items()
                for cell, required_count in cells.items()
                if required_count > 0
            ),
            key=lambda item: (item[0], item[1], item[2]),
        )
        for _supply, axis, cell, required_count in cell_requests:
            matches = sorted(
                (
                    record for record in eligible
                    if str(
                        _value(record.record, axis, "unclassified")
                    ) == cell
                ),
                key=lambda record: (
                    not record.cheap_hard_pass,
                    -record.score,
                    record.key,
                ),
            )
            for record in matches[:required_count]:
                admit(record)

        # Outstanding-cell utility precedes performance.  This cannot evict a
        # protected anchor and gives multi-deficit records deterministic value.
        while (
            len(selected) < min(
                self.exact_shortlist_maximum,
                len(eligible),
            )
            and len(selected) < self.exact_shortlist_minimum
        ):
            outstanding = {
                (axis, cell): max(
                    0,
                    count - self._cell_count(selected, axis, cell),
                )
                for axis, cells in required.items()
                for cell, count in cells.items()
            }
            remaining = [
                record for record in eligible
                if record.key not in selected_keys
            ]
            if not remaining:
                break
            best = max(
                remaining,
                key=lambda record: (
                    sum(
                        shortfall
                        for (axis, cell), shortfall in outstanding.items()
                        if shortfall
                        and str(
                            _value(
                                record.record,
                                axis,
                                "unclassified",
                            )
                        ) == cell
                    ),
                    record.cheap_hard_pass,
                    record.score,
                    -eligible.index(record),
                ),
            )
            admit(best)

        # Use the remaining exact budget for balanced breadth rather than
        # collapsing back to score order.
        for record in (*passed, *exact_required):
            admit(record)
        # Anchor admission controls membership, never exact execution order.
        # Re-emit the protected set through the six-scope round robin.
        selected = [
            record for record in eligible
            if record.key in selected_keys
        ]

        deficits: list[BreadthDeficit] = []
        for axis, cells in required.items():
            for cell, required_count in cells.items():
                available = self._cell_count(selected, axis, cell)
                if available < required_count:
                    deficits.append(BreadthDeficit(
                        axis=axis,
                        cell=cell,
                        required_count=required_count,
                        available_count=available,
                        stage="exact_shortlist_supply",
                        page_index=int(page_index),
                    ))
        distinct_requirements = {
            "body_family": int(
                self.contract.body_phenotype_minimum_distinct
            ),
            "roof_family": int(
                self.contract.roof_archetype_minimum_distinct
            ),
            "chassis_family": int(
                self.contract.chassis_family_minimum_distinct
            ),
            "plan_family": int(
                self.contract.plan_family_minimum_distinct
            ),
            "book_principle_id": (
                10 if self.target_count == 20 else 0
            ),
        }
        for axis, required_count in distinct_requirements.items():
            if required_count <= 0:
                continue
            available_count = len({
                str(_value(record.record, axis, "unclassified"))
                for record in selected
            })
            if available_count < required_count:
                deficits.append(BreadthDeficit(
                    axis=axis,
                    cell="__distinct__",
                    required_count=required_count,
                    available_count=available_count,
                    stage="exact_shortlist_supply",
                    page_index=int(page_index),
                ))
        if len(selected) < self.exact_shortlist_minimum:
            deficits.append(BreadthDeficit(
                axis="exact_shortlist",
                cell="total",
                required_count=self.exact_shortlist_minimum,
                available_count=len(selected),
                stage="exact_shortlist_supply",
                page_index=int(page_index),
            ))
        deficits.sort(key=lambda item: (item.axis, item.cell, item.stage))
        next_page_index = int(page_index) + 1 if deficits else None
        return BreadthScheduleResult(
            cheap_screen_records=screened,
            exact_shortlist=tuple(record.record for record in selected),
            deficits=tuple(deficits),
            stage_failure_counts=MappingProxyType({
                stage: int(stage_counts.get(stage, 0))
                for stage in STAGE_FAILURE_NAMES
            }),
            page_index=int(page_index),
            next_page_index=next_page_index,
        )

    @staticmethod
    def exact_pool_ready(
        *,
        exact_hard_pass_count: int,
        feasible_portfolio: bool,
    ) -> bool:
        """Stop only after the bounded reserve contains a feasible 20-set."""

        return bool(
            feasible_portfolio
            and EXACT_HARD_PASS_MINIMUM
            <= int(exact_hard_pass_count)
            <= EXACT_HARD_PASS_MAXIMUM
        )


__all__ = [
    "BreadthCoordinate",
    "BreadthDeficit",
    "BreadthScheduleResult",
    "CHEAP_EVALUATION_LIMIT",
    "CompetitionBreadthScheduler",
    "EXACT_HARD_PASS_MAXIMUM",
    "EXACT_HARD_PASS_MINIMUM",
    "EXACT_SHORTLIST_MAXIMUM",
    "EXACT_SHORTLIST_MINIMUM",
    "STAGE_FAILURE_NAMES",
    "cheap_screen_records",
]
