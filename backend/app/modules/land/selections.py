"""The site the user picked on the map: a bundle of parcels (they may be merged).

Only the facts shown on the selection card, where each came from and the
adjacency verdict are stored (see the `site_selections` table in
repository.py); geometry is fetched again by PNU.
"""
from datetime import datetime, timezone
import json
import re
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from .pnu import normalize_pnu

MAX_PARCELS = 50
# A scope is a project id, or 'default' for sites picked outside a project.
SCOPE_PATTERN = r'^[A-Za-z0-9_.-]{1,64}$'
DEFAULT_SCOPE = 'default'


class ParcelPick(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', allow_inf_nan=False)
    pnu: str = Field(min_length=1, max_length=100)
    lng: float = Field(ge=124, le=133)
    lat: float = Field(ge=33, le=44)


class SelectionRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    # Over MAX_PARCELS is a 400 from check_parcels; this bound only caps the body size.
    parcels: list[ParcelPick] = Field(min_length=1, max_length=1000)
    label: str = Field(default='', max_length=200)
    scope: str = Field(default=DEFAULT_SCOPE, pattern=SCOPE_PATTERN)


def check_parcels(body: SelectionRequest) -> list[dict]:
    """The picks in the user's order with normalized PNUs; ValueError for a bad, repeated or excess PNU."""
    if len(body.parcels) > MAX_PARCELS:
        raise ValueError(f'A site holds at most {MAX_PARCELS} parcels')
    picks = [{'pnu': normalize_pnu(pick.pnu), 'lng': pick.lng, 'lat': pick.lat} for pick in body.parcels]
    if len({pick['pnu'] for pick in picks}) != len(picks):
        raise ValueError('Each parcel may appear once')
    return picks


def site_label(label: str, parcels: list[dict]) -> str:
    if label.strip():
        return label.strip()
    first = parcels[0]['address'] or parcels[0]['pnu']
    return first if len(parcels) == 1 else f'{first} 외 {len(parcels) - 1}필지'


def save_selection(repository, site: dict, scope: str = DEFAULT_SCOPE) -> dict:
    """Stores a described site (see selection_facts.describe_site) under `scope`, without its geometry."""
    _check_scope(scope)
    record = {'selection_id': str(uuid4()), 'created_at': datetime.now(timezone.utc).isoformat(), 'scope': scope,
              'label': site['label'], 'parcel_count': len(site['parcels']),
              'total_area_m2': site['total_area_m2'], 'contiguous': site['contiguous']}
    parcels = json.dumps(site['parcels'], ensure_ascii=False, allow_nan=False)
    source = json.dumps(site['source'], ensure_ascii=False, allow_nan=False)
    contiguous = None if site['contiguous'] is None else int(site['contiguous'])
    with repository._transaction() as db:
        db.execute('INSERT INTO site_selections (selection_id, created_at, label, parcel_count, total_area_m2, '
                   'contiguous, parcels_json, source_json, scope) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                   (record['selection_id'], record['created_at'], record['label'], record['parcel_count'],
                    record['total_area_m2'], contiguous, parcels, source, scope))
    return _with_derived({**record, 'parcels': json.loads(parcels), 'source': json.loads(source)})


def list_selections(repository, limit: int = 20, scope: str | None = None) -> list[dict]:
    """Newest first; only `scope`'s sites when given, every scope otherwise."""
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('limit must be 1..100')
    if scope is not None:
        _check_scope(scope)
    where, parameters = (' WHERE scope=?', [scope]) if scope is not None else ('', [])
    with repository._transaction() as db:
        rows = db.execute('SELECT * FROM site_selections' + where + ' ORDER BY created_at DESC, rowid DESC LIMIT ?',
                          parameters + [limit]).fetchall()
    return [_record(row) for row in rows]


def _record(row) -> dict:
    return _with_derived({
        'selection_id': row['selection_id'], 'created_at': row['created_at'], 'scope': row['scope'],
        'label': row['label'],
        'parcel_count': row['parcel_count'], 'total_area_m2': row['total_area_m2'],
        'contiguous': None if row['contiguous'] is None else bool(row['contiguous']),
        'parcels': json.loads(row['parcels_json']), 'source': json.loads(row['source_json'])})


def _check_scope(scope) -> None:
    if not isinstance(scope, str) or re.fullmatch(SCOPE_PATTERN, scope) is None:
        raise ValueError('scope must be 1..64 of A-Z a-z 0-9 _ . -')


def _with_derived(site: dict) -> dict:
    zones = list(dict.fromkeys(zone for parcel in site['parcels'] for zone in parcel['summary']['zones']))
    return {**site, 'zones': zones}
