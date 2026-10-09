"""Every page of one law.go.kr ordinance search (DRF lawSearch.do, target=ordin).

The official API lists at most 100 records a page and keeps two edition sets apart: `nw=1` the editions in
force now, `nw=2` the historical ones. A search here walks every page of one set up to `page_limit`, and
says so: `complete` is true only when the last page was reached without an error; a hit page limit or a
transport failure is reported, never hidden. Records keep the official fields; the request's OC id is
stripped from any link or message. Successful results are remembered in process for a short while.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request

from backend.app.modules.law.reference.ordinance_discovery import public_record

PAGE_SIZE = 100
EDITION_SETS = {'current': 1, 'history': 2}
SOURCE = 'law.go.kr DRF lawSearch.do target=ordin'
CACHE_TTL_S = 600
_cache: dict[tuple[str, str], tuple[float, dict]] = {}
_lock = threading.Lock()


def law_oc(env=os.environ) -> str:
    """The law.go.kr open-API user id; empty when not configured (callers refuse rather than guess)."""
    return env.get('LAW_API_OC') or env.get('LAW_OC') or ''


def fetch_page(params: dict, *, oc: str, timeout: float = 30.0) -> dict:
    url = 'https://www.law.go.kr/DRF/lawSearch.do?' + urllib.parse.urlencode(
        {'OC': oc, 'target': 'ordin', 'type': 'JSON', 'display': PAGE_SIZE, **params})
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.load(response)


def _safe(message: str) -> str:
    return re.sub(r'OC=[^&\s]+', 'OC=***', message, flags=re.IGNORECASE)


def search_all(query: str, edition_set: str, *, fetch_json, page_limit: int = 20, now=time.time) -> dict:
    """{rows, pages, total, complete, error} for one query in one edition set, all pages walked."""
    key = (query, edition_set)
    with _lock:
        cached = _cache.get(key)
    if cached and now() - cached[0] < CACHE_TTL_S:
        return cached[1]
    nw = EDITION_SETS[edition_set]
    rows: list[dict] = []
    total, pages, error, complete = None, 0, None, False
    try:
        for page in range(1, page_limit + 1):
            payload = fetch_json({'query': query, 'nw': nw, 'page': page})
            search = payload.get('OrdinSearch') if isinstance(payload, dict) else None
            if not isinstance(search, dict):
                raise ValueError('invalid official ordinance response')
            found = search.get('law') or []
            found = [found] if isinstance(found, dict) else found
            if not isinstance(found, list):
                raise ValueError('invalid ordinance result list')
            pages = page
            rows.extend(public_record(row) for row in found if isinstance(row, dict))
            count = str(search.get('totalCnt', ''))
            if count.isdigit():
                total = int(count)
            if not found or (total is not None and page * PAGE_SIZE >= total) or (total is None and len(found) < PAGE_SIZE):
                complete = True
                break
        else:
            error = f'page_limit_reached: {page_limit} pages read, {total} records listed'
    except Exception as exc:  # the caller shows the failure; nothing legal is inferred from it
        error = _safe(f'{type(exc).__name__}: {exc}')
    result = {'rows': rows, 'pages': pages, 'total': total if total is not None else len(rows),
              'complete': complete and error is None, 'error': error}
    if result['complete']:
        with _lock:
            _cache[key] = (now(), result)
    return result


def clear_cache() -> None:
    with _lock:
        _cache.clear()
