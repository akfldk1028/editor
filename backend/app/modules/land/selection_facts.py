"""Fills a picked bundle of parcels with the facts the selection card shows.

Each parcel goes through the existing land services (address and outline from
the Vworld client, land facts through LandAttributes); the outlines are used
here for the adjacency verdict and handed back for drawing, never stored on disk
(see FactsCache for the short in-memory reuse).
"""
import asyncio
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timezone
import sqlite3
import time

from shapely.geometry import mapping, shape
from shapely.ops import unary_union

from backend.app.modules.regulations import zoning_limits
from backend.app.modules.regulations.zoning_catalog import CatalogUnavailable

from .attributes import LandAttributes
from .projection import wgs84_to_utm, utm_to_wgs84
from .selections import site_label

# Parcels whose outlines come within this many metres of each other count as touching.
TOUCH_TOLERANCE_M = 0.05
_CONCURRENCY = 4
# Facts and outlines are remembered in memory per PNU so a growing bundle only asks Vworld for the new parcels.
CACHE_TTL_S = 600
CACHE_MAX_ENTRIES = 500
# Uncached parcels one request may look up (each is an outline lookup plus a land-facts lookup).
MAX_UPSTREAM_PER_REQUEST = 20


def _now():
    return datetime.now(timezone.utc).isoformat()


def _zoning_zones(names):
    """Only 용도지역 (the zones with BCR/FAR limits); districts and overlays stay out of the card."""
    try:
        return [name for name in names if zoning_limits.lookup(name) is not None]
    except (CatalogUnavailable, OSError):
        return list(names)


class FactsCache:
    """Per-PNU facts and outline, in process memory only (Vworld terms forbid storing their data on disk).

    Entries expire after `ttl_s`; past `max_entries` the least recently used is dropped.
    """

    def __init__(self, ttl_s=CACHE_TTL_S, max_entries=CACHE_MAX_ENTRIES, clock=time.monotonic):
        self.ttl_s, self.max_entries, self._clock = ttl_s, max_entries, clock
        self._entries = OrderedDict()

    def get(self, pnu):
        entry = self._entries.get(pnu)
        if entry is None:
            return None
        if self._clock() - entry[0] >= self.ttl_s:
            del self._entries[pnu]
            return None
        self._entries.move_to_end(pnu)
        return entry[1]

    def put(self, pnu, facts):
        self._entries[pnu] = (self._clock(), facts)
        self._entries.move_to_end(pnu)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)

    def clear(self):
        self._entries.clear()

    def __len__(self):
        return len(self._entries)


facts_cache = FactsCache()


class UpstreamBudgetExceeded(ValueError):
    """More uncached parcels in one request than MAX_UPSTREAM_PER_REQUEST."""


async def _fetch(services, local, pnu, gate):
    """Outline, address and land facts for one PNU: two upstream lookups, no reverse geocode (the PNU is known)."""
    async with gate:
        outline = await services.addresses.fetch_parcel_geometry(pnu)
        geometry_at = _now()
        land = await LandAttributes(services.attributes, local).get(pnu)
        land_at = _now()
    found = outline.get('success') is True and bool(outline.get('geometry'))
    geometry = outline.get('geometry') if found else None
    address = (outline.get('address') or '') if found else ''
    ok = land.get('success') is True
    area = land.get('land_area_m2') if ok else None
    summary = {'address': address, 'land_category': (land.get('land_use_situation') or None) if ok else None,
               'area_m2': area if isinstance(area, (int, float)) else None,
               'zones': _zoning_zones(land.get('zones') or []) if ok else []}
    cache = land.get('cache') or {}
    source = {'address': {'via': 'vworld LP_PA_CBND_BUBUN addr (by PNU)', 'found': bool(address),
                          'fetched_at': geometry_at},
              'land': {'via': 'vworld land attributes (LandAttributes)', 'provider': land.get('source', ''),
                       'stale_cache': bool(cache.get('stale')),
                       'fetched_at': cache.get('fetched_at') if cache.get('stale') else land_at},
              'outline': {'via': 'vworld LP_PA_CBND_BUBUN', 'used_for': 'adjacency, not stored',
                          'found': geometry is not None, 'fetched_at': geometry_at}}
    facts = {'address': address, 'summary': summary, 'source': source, 'geometry': geometry}
    # Only complete, live answers are remembered; a gap or an outage is asked again next time.
    if geometry is not None and ok and not cache.get('stale'):
        facts_cache.put(pnu, facts)
    return facts


def _described(pick, facts):
    parcel = {'pnu': pick['pnu'], 'address': facts['address'], 'lng': pick['lng'], 'lat': pick['lat'],
              'summary': deepcopy(facts['summary'])}
    return parcel, deepcopy(facts['source']), facts['geometry']


def contiguity(geometries):
    """True when the outlines form one connected group (touching within TOUCH_TOLERANCE_M), None if any is missing."""
    if any(geometry is None for geometry in geometries):
        return None
    shapes = [wgs84_to_utm(shape(geometry)).buffer(TOUCH_TOLERANCE_M / 2) for geometry in geometries]
    reached, frontier = {0}, [0]
    while frontier:
        current = frontier.pop()
        for other, candidate in enumerate(shapes):
            if other not in reached and shapes[current].intersects(candidate):
                reached.add(other)
                frontier.append(other)
    return len(reached) == len(shapes)


def merged_outline(geometries):
    """The bundle's combined boundary in WGS84 (for drawing only)."""
    present = [wgs84_to_utm(shape(geometry)).buffer(TOUCH_TOLERANCE_M / 2) for geometry in geometries if geometry]
    if not present:
        return None
    return mapping(utm_to_wgs84(unary_union(present).buffer(-TOUCH_TOLERANCE_M / 2)))


outline_cache = FactsCache()


async def site_outlines(services, pnus):
    """Outlines (and their merged boundary) of an already described site, for redrawing a saved one.

    The saved record keeps the facts, so only outlines are asked again: one lookup per parcel not
    in memory, bounded by the site size itself (MAX_PARCELS, checked by the caller).
    """
    known = {}
    for pnu in pnus:
        facts = facts_cache.get(pnu)
        known[pnu] = facts['geometry'] if facts else outline_cache.get(pnu)
    missing = [pnu for pnu, geometry in known.items() if geometry is None]
    gate = asyncio.Semaphore(_CONCURRENCY)

    async def fetch(pnu):
        async with gate:
            answer = await services.addresses.fetch_parcel_geometry(pnu)
        geometry = answer.get('geometry') if answer.get('success') is True else None
        if geometry:
            outline_cache.put(pnu, geometry)
        return geometry

    known.update(zip(missing, await asyncio.gather(*(fetch(pnu) for pnu in missing))))
    geometries = [known[pnu] for pnu in pnus]
    return {'geometries': dict(known), 'outline': merged_outline(geometries)}


async def describe_site(services, picks, label=''):
    try:
        local = services.local_repository()
    except (OSError, ValueError, sqlite3.Error):
        local = None
    known = {pick['pnu']: facts_cache.get(pick['pnu']) for pick in picks}
    missing = [pnu for pnu, facts in known.items() if facts is None]
    if len(missing) > MAX_UPSTREAM_PER_REQUEST:
        raise UpstreamBudgetExceeded(f'At most {MAX_UPSTREAM_PER_REQUEST} new parcels can be looked up per '
                                     f'request ({len(missing)} asked); add them in smaller steps')
    gate = asyncio.Semaphore(_CONCURRENCY)
    fetched = await asyncio.gather(*(_fetch(services, local, pnu, gate) for pnu in missing))
    known.update(zip(missing, fetched))
    described = [_described(pick, known[pick['pnu']]) for pick in picks]
    parcels = [parcel for parcel, _, _ in described]
    geometries = [geometry for _, _, geometry in described]
    areas = [parcel['summary']['area_m2'] for parcel in parcels]
    return {'label': site_label(label, parcels), 'parcels': parcels,
            'total_area_m2': round(sum(areas), 2) if all(area is not None for area in areas) else None,
            'contiguous': contiguity(geometries),
            'zones': list(dict.fromkeys(zone for parcel in parcels for zone in parcel['summary']['zones'])),
            'source': {parcel['pnu']: source for parcel, source, _ in described},
            'geometries': {parcel['pnu']: geometry for parcel, geometry in zip(parcels, geometries)},
            'outline': merged_outline(geometries)}
