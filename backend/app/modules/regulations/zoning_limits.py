"""Preserved zoning-reference calculation; municipal overrides belong to callers.

Overlap thresholds and evidence qualifications are copied from the preserved
source data. These reference results are not an approval or current-law audit.
"""
import json
import math
from pathlib import Path

from .zoning_catalog import CatalogUnavailable, get_zones

OVERLAP_PATH = Path(__file__).with_name('data') / 'zone_overlap_rules.json'


def _load_overlap():
    try:
        rules = json.loads(OVERLAP_PATH.read_text(encoding='utf-8'))
        sections = ('capacity_rule', 'other_restrictions_rule', 'green_zone', 'small_part_threshold')
        if not isinstance(rules, dict) or any(not isinstance(rules.get(key), dict) for key in sections):
            raise ValueError('Invalid overlap rules')
        for section, keys in (
            ('capacity_rule', ('article', 'method')),
            ('green_zone', ('category',)),
            ('small_part_threshold', ('article',)),
        ):
            if any(not isinstance(rules[section].get(key), str) or not rules[section][key] for key in keys):
                raise ValueError('Missing overlap rule field')
        threshold = rules['small_part_threshold']
        size = threshold.get('default_m2')
        if type(size) not in (int, float) or not math.isfinite(size) or size <= 0:
            raise ValueError('Invalid overlap threshold')
        if type(threshold.get('verified_in_corpus')) is not bool:
            raise ValueError('Missing threshold evidence status')
        for branch in ('when_weighted', 'when_each'):
            rule = rules['other_restrictions_rule'].get(branch)
            if not isinstance(rule, dict) or any(not isinstance(rule.get(key), str) or not rule[key]
                                                 for key in ('source_zone', 'article')):
                raise ValueError('Invalid overlap branch')
        return rules
    except (OSError, ValueError, TypeError) as exc:
        raise CatalogUnavailable('Zoning overlap rules unavailable') from exc


def lookup(zone_name: str) -> dict | None:
    return next((zone for zone in get_zones()['zones'] if zone['zone_name'] == zone_name), None)


def is_green_zone(zone: dict) -> bool:
    return zone.get('category') == _load_overlap()['green_zone']['category']


def resolve_limits(zone_names: list[str], zone_areas: dict[str, float] | None = None) -> dict:
    catalog = {zone['zone_name']: zone for zone in get_zones()['zones']}
    matched_zones = []
    unmatched = []
    for name in zone_names:
        zone = catalog.get(name)
        if zone:
            matched_zones.append(zone)
        else:
            unmatched.append(name)
    return combine_limits(matched_zones, zone_areas or {}, unmatched=unmatched)


def combine_limits(
    zones: list[dict], areas: dict[str, float] | None = None, *, unmatched: list[str] | None = None,
) -> dict:
    unmatched = list(unmatched or ())
    areas = areas or {}
    if not zones:
        return {'bcr_limit': None, 'far_limit': None, 'zones': [],
                'matched': 0, 'unmatched': unmatched}
    if len(zones) == 1:
        only = zones[0]
        return {'bcr_limit': only['bcr_default'], 'far_limit': only['far_default'],
                'zones': zones, 'matched': 1, 'unmatched': unmatched}
    rules = _load_overlap()
    known = {z['zone_name']: float(areas.get(z['zone_name'], 0.0)) for z in zones}
    total = sum(known.values())
    if total <= 0.0:
        return {
            'bcr_limit': None, 'far_limit': None, 'zones': zones,
            'matched': len(zones), 'unmatched': unmatched,
            'overlap': {
                'article': rules['capacity_rule']['article'], 'needs_zone_areas': True,
                'reason': ('대지가 둘 이상의 용도지역에 걸쳐 있어 제84조가 적용되며, '
                           '용도지역별 면적 없이는 건폐율·용적률을 산정할 수 없다'),
            },
        }
    bcr = sum(z['bcr_default'] * known[z['zone_name']] for z in zones) / total
    far = sum(z['far_default'] * known[z['zone_name']] for z in zones) / total
    smallest = min(zones, key=lambda z: known[z['zone_name']])
    threshold = float(rules['small_part_threshold']['default_m2'])
    green_category = rules['green_zone']['category']
    green = [z for z in zones if z.get('category') == green_category]
    green_is_minor = (bool(green) and smallest.get('category') == green_category
                      and known[smallest['zone_name']] <= threshold)
    per_part = bool(green) and not green_is_minor
    branch = 'when_each' if per_part else 'when_weighted'
    other = rules['other_restrictions_rule'][branch]
    largest = max(zones, key=lambda z: known[z['zone_name']])
    return {
        'bcr_limit': round(bcr, 4), 'far_limit': round(far, 4), 'zones': zones,
        'matched': len(zones), 'unmatched': unmatched,
        'overlap': {
            'article': rules['capacity_rule']['article'],
            'capacity_method': rules['capacity_rule']['method'],
            'branch': '제84조제3항' if per_part else '제84조제1항',
            'other_restrictions': {
                'source_zone': None if per_part else largest['zone_name'],
                'rule': other['source_zone'], 'article': other['article'],
            },
            'areas_m2': {name: round(value, 2) for name, value in known.items()},
            'total_area_m2': round(total, 2),
            'smallest_part': {
                'zone_name': smallest['zone_name'],
                'area_m2': round(known[smallest['zone_name']], 2),
                'threshold_m2': threshold,
                'threshold_article': rules['small_part_threshold']['article'],
                'threshold_verified_in_corpus': rules['small_part_threshold']['verified_in_corpus'],
            },
            'needs_zone_areas': False,
        },
    }
