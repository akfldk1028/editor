"""One HTTP look at a health URL: up or down, and which version answers. Never raises."""
from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

import httpx

TIMEOUT_SECONDS = 3.0
CONCURRENCY = 8
CACHE_SECONDS = 20.0


@dataclass(frozen=True)
class Probe:
    state: str  # up | down | unknown
    http_status: int | None
    version: str | None
    started_at: str | None
    latency_ms: int | None
    error: str | None
    checked_at: str

    def as_dict(self) -> dict:
        return asdict(self)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _pick(body, keys) -> str | None:
    if not isinstance(body, dict):
        return None
    for key in keys:
        value = body.get(key)
        if isinstance(value, str) and value:
            return value
    return None


class Prober:
    """Probes URLs concurrently (at most CONCURRENCY at once) and remembers each answer for
    `cache_seconds`; `probe_all(force=True)` asks again regardless."""

    def __init__(self, *, transport=None, timeout: float = TIMEOUT_SECONDS,
                 cache_seconds: float = CACHE_SECONDS, clock=time.monotonic):
        self.transport = transport
        self.timeout = timeout
        self.cache_seconds = cache_seconds
        self.clock = clock
        self._cache: dict[str, tuple[float, Probe]] = {}

    async def probe_all(self, urls: dict[str, str | None], *, force: bool = False) -> dict[str, Probe]:
        now = self.clock()
        results: dict[str, Probe] = {}
        pending: dict[str, str] = {}
        for key, url in urls.items():
            if url is None:
                results[key] = Probe('unknown', None, None, None, None, 'no health URL', _now())
                continue
            cached = self._cache.get(url)
            if cached and not force and now - cached[0] < self.cache_seconds:
                results[key] = cached[1]
            else:
                pending[key] = url
        if pending:
            semaphore = asyncio.Semaphore(CONCURRENCY)
            async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport,
                                         follow_redirects=False) as client:
                async def one(key, url):
                    async with semaphore:
                        results[key] = await self.probe(client, url)
                await asyncio.gather(*(one(key, url) for key, url in pending.items()))
            stamp = self.clock()
            for key, url in pending.items():
                self._cache[url] = (stamp, results[key])
        return results

    async def probe(self, client: httpx.AsyncClient, url: str) -> Probe:
        started = time.perf_counter()
        try:
            response = await client.get(url, headers={'accept': 'application/json'})
        except Exception as exc:  # noqa: BLE001 - a probe reports, never raises
            latency = int((time.perf_counter() - started) * 1000)
            return Probe('down', None, None, None, latency, type(exc).__name__, _now())
        latency = int((time.perf_counter() - started) * 1000)
        body = None
        if 'json' in (response.headers.get('content-type') or ''):
            try:
                body = response.json()
            except ValueError:
                body = None
        state = 'up' if 200 <= response.status_code < 300 else 'down'
        return Probe(state, response.status_code, _pick(body, ('version', 'git_sha')),
                     _pick(body, ('started_at', 'startedAt')), latency,
                     None if state == 'up' else f'HTTP {response.status_code}', _now())
