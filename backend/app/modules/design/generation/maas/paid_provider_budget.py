"""Process-wide accounting for actual paid provider network requests."""

from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
import os
from threading import Lock
from typing import Any


PAID_PROVIDER_BUDGET_SCHEMA = "arr.maas.paid_provider_budget.v1"
_DEFAULT_LIMIT = 256
_MAXIMUM_LIMIT = 256
_LOCK = Lock()
_QUOTA_NAMES = (
    "author_initial",
    "author_replenishment",
    "base_candidate",
    "exact_candidate",
    "portfolio_board",
    "reference_audit",
    "retry",
)
_REQUEST_QUOTA_BY_KIND = {
    "geometry_author_initial": "author_initial",
    "geometry_author_replenishment": "author_replenishment",
    "base_candidate_vlm": "base_candidate",
    "exact_candidate_vlm": "exact_candidate",
    "final_pair_vlm": "exact_candidate",
    "portfolio_vlm": "portfolio_board",
    "reference_audit_vlm": "reference_audit",
    "retry": "retry",
    "provider_retry": "retry",
}


class PaidProviderBudgetError(RuntimeError):
    """Raised before a paid network request would exceed its hard ceiling."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        request_kind: str,
        quota: str,
        used: int | None,
        limit: int | None,
        remaining: int | None,
    ):
        self.code = str(code)
        self.request_kind = str(request_kind)
        self.quota = str(quota)
        self.used = None if used is None else int(used)
        self.limit = None if limit is None else int(limit)
        self.remaining = None if remaining is None else int(remaining)
        super().__init__(str(message)[:500])


@dataclass
class _PaidProviderBudgetState:
    limit: int
    request_count: int = 0
    request_counts_by_kind: Counter[str] = field(default_factory=Counter)
    quota_limits: dict[str, int] | None = None
    quota_request_counts: Counter[str] = field(default_factory=Counter)
    run_metadata: dict[str, Any] = field(default_factory=dict)


def _environment_limit() -> int:
    try:
        value = int(os.getenv(
            "MAAS_PAID_PROVIDER_MAX_REQUESTS",
            str(_DEFAULT_LIMIT),
        ))
    except (TypeError, ValueError):
        value = _DEFAULT_LIMIT
    return max(1, min(_MAXIMUM_LIMIT, value))


_STATE = _PaidProviderBudgetState(limit=_environment_limit())


def _snapshot_unlocked() -> dict[str, Any]:
    snapshot = {
        "schema_version": PAID_PROVIDER_BUDGET_SCHEMA,
        "limit": _STATE.limit,
        "request_count": _STATE.request_count,
        "remaining_count": max(0, _STATE.limit - _STATE.request_count),
        "request_counts_by_kind": dict(sorted(
            _STATE.request_counts_by_kind.items()
        )),
    }
    if _STATE.quota_limits is not None:
        snapshot.update({
            "quota_limits": dict(_STATE.quota_limits),
            "quota_request_counts": {
                name: int(_STATE.quota_request_counts.get(name, 0))
                for name in _QUOTA_NAMES
            },
            "quota_remaining_counts": {
                name: max(
                    0,
                    limit - int(_STATE.quota_request_counts.get(name, 0)),
                )
                for name, limit in _STATE.quota_limits.items()
            },
            "run_metadata": dict(_STATE.run_metadata),
        })
    return snapshot


def configure_paid_provider_budget(
    limit: int,
    *,
    quotas: dict[str, int] | None = None,
    run_metadata: dict[str, Any] | None = None,
) -> None:
    resolved = int(limit)
    if resolved < 1 or resolved > _MAXIMUM_LIMIT:
        raise ValueError(
            f"paid provider request limit must be between 1 and "
            f"{_MAXIMUM_LIMIT}"
        )
    resolved_quotas: dict[str, int] | None = None
    if quotas is not None:
        if set(quotas) != set(_QUOTA_NAMES):
            raise ValueError(
                "paid provider quotas must define exactly:"
                + ",".join(_QUOTA_NAMES)
            )
        resolved_quotas = {}
        for name in _QUOTA_NAMES:
            value = quotas[name]
            if isinstance(value, bool):
                raise ValueError(f"paid provider quota must be an integer:{name}")
            try:
                quota = int(value)
            except (TypeError, ValueError):
                raise ValueError(
                    f"paid provider quota must be an integer:{name}"
                ) from None
            if quota < 0 or quota != value:
                raise ValueError(
                    f"paid provider quota must be a non-negative integer:{name}"
                )
            resolved_quotas[name] = quota
        if sum(resolved_quotas.values()) != resolved:
            raise ValueError(
                "paid provider quota total must equal request limit:"
                f"{sum(resolved_quotas.values())}/{resolved}"
            )
    with _LOCK:
        if _STATE.request_count:
            raise PaidProviderBudgetError(
                "paid_provider_budget_already_consumed:"
                f"{_STATE.request_count}",
                code="budget_already_consumed",
                request_kind="configure",
                quota="total",
                used=_STATE.request_count,
                limit=_STATE.limit,
                remaining=max(0, _STATE.limit - _STATE.request_count),
            )
        _STATE.limit = resolved
        _STATE.request_counts_by_kind.clear()
        _STATE.quota_limits = resolved_quotas
        _STATE.quota_request_counts.clear()
        _STATE.run_metadata = dict(run_metadata or {})


@contextmanager
def paid_provider_budget_scope(
    limit: int,
    *,
    quotas: dict[str, int],
    run_metadata: dict[str, Any] | None = None,
    environment_updates: dict[str, str] | None = None,
):
    """Install one run-local ledger and restore all process state afterward."""

    resolved = int(limit)
    previous_environment = {
        key: os.environ.get(key)
        for key in (environment_updates or {})
    }
    with _LOCK:
        previous = _PaidProviderBudgetState(
            limit=_STATE.limit,
            request_count=_STATE.request_count,
            request_counts_by_kind=Counter(_STATE.request_counts_by_kind),
            quota_limits=(
                dict(_STATE.quota_limits)
                if _STATE.quota_limits is not None
                else None
            ),
            quota_request_counts=Counter(_STATE.quota_request_counts),
            run_metadata=dict(_STATE.run_metadata),
        )
        _STATE.request_count = 0
        _STATE.request_counts_by_kind.clear()
        _STATE.quota_request_counts.clear()
        _STATE.quota_limits = None
        _STATE.run_metadata.clear()
    try:
        configure_paid_provider_budget(
            resolved,
            quotas=quotas,
            run_metadata=run_metadata,
        )
        for key, value in (environment_updates or {}).items():
            os.environ[key] = str(value)
        yield paid_provider_budget_snapshot()
    finally:
        with _LOCK:
            _STATE.limit = previous.limit
            _STATE.request_count = previous.request_count
            _STATE.request_counts_by_kind = Counter(
                previous.request_counts_by_kind
            )
            _STATE.quota_limits = (
                dict(previous.quota_limits)
                if previous.quota_limits is not None
                else None
            )
            _STATE.quota_request_counts = Counter(
                previous.quota_request_counts
            )
            _STATE.run_metadata = dict(previous.run_metadata)
        for key, previous_value in previous_environment.items():
            if previous_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous_value


def reserve_paid_provider_request(kind: str) -> dict[str, Any]:
    normalized = str(kind or "").strip()
    if not normalized:
        raise ValueError("paid provider request kind is required")
    with _LOCK:
        quota_name: str | None = None
        if _STATE.quota_limits is not None:
            quota_name = _REQUEST_QUOTA_BY_KIND.get(normalized)
            if quota_name is None:
                raise PaidProviderBudgetError(
                    f"paid_provider_request_kind_unpartitioned:{normalized}",
                    code="request_kind_unpartitioned",
                    request_kind=normalized,
                    quota="unpartitioned",
                    used=_STATE.request_count,
                    limit=_STATE.limit,
                    remaining=max(0, _STATE.limit - _STATE.request_count),
                )
            consumed = int(_STATE.quota_request_counts.get(quota_name, 0))
            quota_limit = int(_STATE.quota_limits[quota_name])
            if consumed >= quota_limit:
                raise PaidProviderBudgetError(
                    "paid_provider_request_quota_exhausted:"
                    f"kind={normalized}:quota={quota_name}:"
                    f"{consumed}/{quota_limit}",
                    code="request_quota_exhausted",
                    request_kind=normalized,
                    quota=quota_name,
                    used=consumed,
                    limit=quota_limit,
                    remaining=max(0, quota_limit - consumed),
                )
        if _STATE.request_count >= _STATE.limit:
            raise PaidProviderBudgetError(
                "paid_provider_request_budget_exhausted:"
                f"{_STATE.request_count}/{_STATE.limit}",
                code="total_budget_exhausted",
                request_kind=normalized,
                quota="total",
                used=_STATE.request_count,
                limit=_STATE.limit,
                remaining=max(0, _STATE.limit - _STATE.request_count),
            )
        _STATE.request_count += 1
        _STATE.request_counts_by_kind[normalized] += 1
        if quota_name is not None:
            _STATE.quota_request_counts[quota_name] += 1
        return _snapshot_unlocked()


def paid_provider_budget_snapshot() -> dict[str, Any]:
    with _LOCK:
        return _snapshot_unlocked()


def reset_paid_provider_budget_for_tests() -> None:
    with _LOCK:
        _STATE.limit = _environment_limit()
        _STATE.request_count = 0
        _STATE.request_counts_by_kind.clear()
        _STATE.quota_limits = None
        _STATE.quota_request_counts.clear()
        _STATE.run_metadata.clear()


__all__ = [
    "PAID_PROVIDER_BUDGET_SCHEMA",
    "PaidProviderBudgetError",
    "configure_paid_provider_budget",
    "paid_provider_budget_snapshot",
    "paid_provider_budget_scope",
    "reserve_paid_provider_request",
    "reset_paid_provider_budget_for_tests",
]
