from copy import deepcopy
import sqlite3

from starlette.concurrency import run_in_threadpool
from .pnu import normalize_pnu


class LandAttributes:
    def __init__(self, provider, repository=None):
        self.provider = provider
        self.repository = repository

    async def get(self, pnu: str) -> dict:
        pnu = normalize_pnu(pnu)
        result = deepcopy(await self.provider.fetch(pnu))
        cached = None
        saved = False
        if self.repository is not None:
            try:
                if result['success'] and result.get('zones_fetched') and result['zones']:
                    await run_in_threadpool(self.repository.put_land_cache, pnu, result)
                    saved = True
                elif not result['success']:
                    cached = await run_in_threadpool(self.repository.get_land_cache, pnu)
            except (OSError, ValueError, TypeError, sqlite3.Error):
                pass
        # Partial live responses remain authoritative; fallback occurs only on total outage.
        if cached:
            return {**cached['result'], 'errors': list(dict.fromkeys(
                        cached['result'].get('errors', []) + result.get('errors', []))),
                    'cache': {'stale': True, 'fetched_at': cached['fetched_at'], 'saved': False}}
        return {**result, 'cache': {'stale': False, 'saved': saved}}
