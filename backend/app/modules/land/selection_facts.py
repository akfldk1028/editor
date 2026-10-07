"""Fills a picked bundle of parcels with the facts the selection card shows.

Each parcel goes through the existing land services (address and outline from
the Vworld client, land facts through LandAttributes); the outlines are used
here for the adjacency verdict and handed back for drawing, never stored.
"""
import asyncio
from datetime import datetime, timezone
import sqlite3

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


def _now():
    return datetime.now(timezone.utc).isoformat()


def _zoning_zones(names):
    """Only 용도지역 (the zones with BCR/FAR limits); districts and overlays stay out of the card."""
    try:
        return [name for name in names if zoning_limits.lookup(name) is not None]
    except (CatalogUnavailable, OSError):
        return list(names)


async def _describe(services, local, pick, gate):
    async with gate:
        pnu = pick['pnu']
        located = await services.addresses.reverse_geocode(pick['lng'], pick['lat'])
        matched = located.get('success') and located.get('pnu') == pnu
        address = (located.get('address') or '') if matched else ''
        address_at = _now()
        geometry = located.get('geometry') if matched else None
        if not geometry:
            outline = await services.addresses.fetch_parcel_geometry(pnu)
            geometry = outline.get('geometry') if outline.get('success') else None
        geometry_at = _now()
        land = await LandAttributes(services.attributes, local).get(pnu)
        land_at = _now()
    ok = land.get('success') is True
    area = land.get('land_area_m2') if ok else None
    summary = {'address': address, 'land_category': (land.get('land_use_situation') or None) if ok else None,
               'area_m2': area if isinstance(area, (int, float)) else None,
               'zones': _zoning_zones(land.get('zones') or []) if ok else []}
    cache = land.get('cache') or {}
    source = {'address': {'via': 'vworld getAddress (POST /land/reverse)', 'matched_pnu': bool(matched),
                          'fetched_at': address_at},
              'land': {'via': 'vworld land attributes (LandAttributes)', 'provider': land.get('source', ''),
                       'stale_cache': bool(cache.get('stale')),
                       'fetched_at': cache.get('fetched_at') if cache.get('stale') else land_at},
              'outline': {'via': 'vworld LP_PA_CBND_BUBUN', 'used_for': 'adjacency, not stored',
                          'found': geometry is not None, 'fetched_at': geometry_at}}
    return {'pnu': pnu, 'address': address, 'lng': pick['lng'], 'lat': pick['lat'], 'summary': summary}, \
        source, geometry


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


async def describe_site(services, picks, label=''):
    try:
        local = services.local_repository()
    except (OSError, ValueError, sqlite3.Error):
        local = None
    gate = asyncio.Semaphore(_CONCURRENCY)
    described = await asyncio.gather(*(_describe(services, local, pick, gate) for pick in picks))
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
