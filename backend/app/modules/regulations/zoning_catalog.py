import json
import math
from pathlib import Path


DATA_PATH = Path(__file__).with_name('data') / 'zoning_limits.json'


class CatalogUnavailable(Exception):
    pass


def get_zones() -> dict:
    try:
        payload = json.loads(DATA_PATH.read_text(encoding='utf-8'))
        zones = payload['zones']
        if not isinstance(zones, list) or not zones:
            raise ValueError('Empty or invalid catalog')
        names = set()
        for zone in zones:
            if not isinstance(zone, dict):
                raise ValueError('Invalid zone')
            name = zone.get('zone_name')
            if not isinstance(name, str) or not name.strip() or name in names:
                raise ValueError('Invalid or duplicate zone name')
            names.add(name)
            for field in ('bcr_default', 'far_default'):
                value = zone.get(field)
                if type(value) not in (int, float) or not math.isfinite(value):
                    raise ValueError('Invalid zone value')
        return {'zones': zones, 'count': len(zones)}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise CatalogUnavailable('Zoning catalog unavailable') from exc
