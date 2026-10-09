"""Which local governments' ordinances can bind a parcel.

The levels come from the parcel's registry address (Vworld 연속지적도 `addr`, looked up by PNU — never from a
label the screen shows): the 시·도, then the 시·군·자치구. A 일반구 (a 구 inside a 시) issues no ordinance,
so it is noted and its 시 is the level. Each level is cross-checked against the PNU's codes through the
ordinance snapshots the Law domain already holds (`ordinance_overrides/<code>.json`, generated from
law.go.kr): a snapshot naming a different government is a conflict and the level fails closed. No city,
code or list of municipalities is written here.
"""
from __future__ import annotations

import json
import re

from backend.app.modules.regulations.calculator import ORDINANCE_DIR

_SIDO = re.compile(r'(특별시|광역시|특별자치시|특별자치도|도)$')
_SIGUNGU = re.compile(r'(시|군|구)$')
_BELOW = re.compile(r'(읍|면|동|리|가|로|길)$')


def _norm(value) -> str:
    return re.sub(r'\s+', '', str(value or ''))


def levels_from_address(address: str | None) -> dict:
    """{levels: [{level, name, issuer}], notes: [], reason} — the governments named by a registry address."""
    tokens = str(address or '').split()
    if len(tokens) < 2 or not _SIDO.search(tokens[0]):
        return {'levels': [], 'notes': [], 'reason': 'address_not_parsable'}
    sido = tokens[0]
    levels = [{'level': 'sido', 'name': sido, 'issuer': sido}]
    notes: list[str] = []
    second = tokens[1]
    if _SIGUNGU.search(second) and not _BELOW.search(second):
        levels.append({'level': 'sigungu', 'name': second, 'issuer': f'{sido} {second}'})
        third = tokens[2] if len(tokens) > 2 else ''
        if second.endswith('시') and third.endswith('구') and not _BELOW.search(third):
            notes.append(f'{third}은(는) {second} 안의 일반구라 자치법규를 내지 않아요 — {second} 조례를 봅니다')
    return {'levels': levels, 'notes': notes, 'reason': None}


def _snapshot(code: str) -> dict | None:
    path = ORDINANCE_DIR / f'{code}.json'
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def cross_check(levels: list[dict], pnu: str) -> list[dict]:
    """Each level gets its PNU code and a `check`: `ordinance_snapshot_match` (the Law domain's snapshot for that
    code names the same government; its law.go.kr issuer string is kept beside the derived one as `snapshot_issuer`),
    `address_only` (no snapshot to compare with) or `conflict` (the snapshot names another government)."""
    sido_code, si_code, sigungu_code = pnu[:2], pnu[:4] + '0', pnu[:5]
    for level in levels:
        code = sido_code if level['level'] == 'sido' else sigungu_code
        snapshot = _snapshot(code)
        if snapshot is None and level['level'] == 'sigungu' and si_code != sigungu_code:
            # A 일반구 code has no snapshot of its own; its 시 does.
            snapshot, code = _snapshot(si_code), si_code
        level['code'] = code
        level['source'] = 'vworld LP_PA_CBND_BUBUN addr'
        if snapshot is None:
            level['check'] = 'address_only'
            continue
        name = snapshot.get('sigungu_name')
        issuer = (snapshot.get('ordinance') or {}).get('issuer') if isinstance(snapshot.get('ordinance'), dict) else None
        if name and _norm(name) != _norm(level['name']):
            level.update({'check': 'conflict', 'snapshot_name': name})
            continue
        level['check'] = 'ordinance_snapshot_match'
        level['source'] += f'; ordinance_overrides/{code}.json'
        if isinstance(issuer, str) and issuer.strip():
            level['snapshot_issuer'] = issuer.strip()
    return levels


def issuers_of(level: dict) -> list[str]:
    """The issuer strings a record may carry for this level: the derived one and, when present, the snapshot's."""
    return [value for value in (level.get('issuer'), level.get('snapshot_issuer')) if isinstance(value, str) and value.strip()]


def resolve(pnu: str, address: str | None) -> dict:
    """{address, status: resolved|unresolved|conflict, reason, levels, notes}. A conflict anywhere fails the whole
    jurisdiction closed: no candidate is verified against a government we are not sure of."""
    parsed = levels_from_address(address)
    if not parsed['levels']:
        return {'address': address, 'status': 'unresolved', 'reason': parsed['reason'] if address else 'address_unavailable',
                'levels': [], 'notes': parsed['notes']}
    levels = cross_check(parsed['levels'], pnu)
    conflicts = [level for level in levels if level['check'] == 'conflict']
    if conflicts:
        return {'address': address, 'status': 'conflict',
                'reason': 'jurisdiction_conflict: ' + ', '.join(f"{c['name']} vs snapshot {c['snapshot_name']} ({c['code']})" for c in conflicts),
                'levels': levels, 'notes': parsed['notes']}
    return {'address': address, 'status': 'resolved', 'reason': None, 'levels': levels, 'notes': parsed['notes']}
