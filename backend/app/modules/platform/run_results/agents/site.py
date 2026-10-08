"""The Site Agent's answer (`site_resolve`), read into the contract's `site` shape.

Facts follow `sitecontextagent/facts.py` SITE_KEYS; a cut answer keeps the first facts of `state_patch`."""
import re

from backend.app.modules.platform.run_results.common import _dict, _num, _str, _strings, _unique

TOOL = 'site_resolve'
AGENT = 'site_context'
_FACTS = re.compile(r'(\d+)\s*/\s*(\d+)\s*site facts')


def _fact_summary(key, value):
    """One short line per site fact the Site Agent stores (`sitecontextagent/facts.py` SITE_KEYS)."""
    value = _dict(value)
    if key == 'site.boundary':
        area = _num(value.get('area_m2'))
        return f'면적 {area:,.2f}㎡' if area is not None else None
    if key == 'site.roads':
        roads = [_dict(f).get('properties') for f in value.get('centrelines') or [] if isinstance(f, dict)]
        widths = _unique(f'{_num(_dict(p).get("width_m")):g}m' for p in roads if _num(_dict(p).get('width_m')) is not None)
        return f'접도 {len(roads)}건' + (f' · 폭 {", ".join(widths)}' if widths else '') if roads else None
    if key == 'site.north':
        bearing = _num(value.get('true_north_deg')) if _num(value.get('true_north_deg')) is not None else _num(value.get('bearing_deg'))
        return f'진북 {bearing:g}°' if bearing is not None else None
    if key == 'site.terrain':
        levels = [_num(v) for v in (value.get('min_m'), value.get('max_m')) if _num(v) is not None]
        return f'표고 {levels[0]:g}~{levels[1]:g} m' if len(levels) == 2 else None
    return None


def _site_facts(response):
    """The facts readable in `state_patch` (a cut response keeps the first ones): key, confidence, provenance, summary."""
    facts = []
    for key, fact in _dict(response.get('state_patch')).items():
        if not isinstance(key, str) or not key.startswith('site.') or not isinstance(fact, dict):
            continue
        facts.append({'key': key, 'confidence': _str(fact.get('confidence')), 'source': _str(fact.get('source')),
                      'as_of': _str(fact.get('as_of')), 'summary': _fact_summary(key, fact.get('value'))})
    return facts


def parse(row, response, rationale):
    if row is None:
        return None
    match = _FACTS.search(_str(response.get('summary')) or '')
    missing = [item['finding'] for item in rationale
               if item['raised_by'] == 'site_context' and item['category'] == 'site_fact_missing' and item['finding']]
    missing += _strings(response.get('missing')) + _strings(response.get('missing_facts'))
    return {'status': _str(response.get('status')) or _str(row.get('state')) or 'unknown', 'code': _str(response.get('code')),
            'facts_known': int(match.group(1)) if match else None, 'facts_total': int(match.group(2)) if match else None,
            'facts_missing': _unique(missing), 'facts': _site_facts(response)}

