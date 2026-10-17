"""Mass's review of MasterPlan's zone (`mass_footprint_alternatives`), read into the site map's `mass_forms` shape.

Mass stands several forms on the building zone MasterPlan placed and says whether any reaches the requested floor
area; when none does, the Orchestrator sends the zone back to MasterPlan once (task `.../mass_revision`) and Mass
reviews the revision. This reads the newest review (the forms a person picks from), the first verdict (why the zone
changed) and the order the owners took, as the pattern the site map draws: 제안 -> 검토 -> 수정 -> 재검토.
"""
from backend.app.modules.platform.run_results.common import _dict, _num, _str

TOOL = 'mass_footprint_alternatives'
AGENT = 'mass'
LAYOUT_TOOL = 'masterplan_layout_synthesize'
REVISION = '/mass_revision'
THUMBNAIL_MAX = 40_000      # characters of SVG; a larger drawing is left out rather than sent to the page


def _alternative(value):
    value = _dict(value)
    svg = _str(value.get('thumbnail_svg'))
    volumes = [{'ring': [[_num(p[0]), _num(p[1])] for p in _dict(v).get('ring') or [] if isinstance(p, list) and len(p) >= 2],
                'base_m': _num(_dict(v).get('base_m')), 'top_m': _num(_dict(v).get('top_m'))}
               for v in value.get('volumes') or [] if isinstance(v, dict)]
    return {'id': _str(value.get('id')), 'form': _str(value.get('form')), 'label': _str(value.get('label')),
            'footprint_m2': _num(value.get('footprint_m2')), 'coverage_of_zone': _num(value.get('coverage_of_zone')),
            'gfa_m2': _num(value.get('gfa_m2')), 'height_m': _num(value.get('height_m')), 'storeys': _num(value.get('storeys')),
            'reaches_target': value.get('reaches_target') if isinstance(value.get('reaches_target'), bool) else None,
            'volumes': [v for v in volumes if len(v['ring']) >= 3 and v['top_m'] is not None and v['base_m'] is not None],
            'thumbnail_svg': svg if svg and svg.lstrip().startswith('<svg') and len(svg) <= THUMBNAIL_MAX else None}


def _verdict(response):
    verdict = _dict(_dict(response).get('verdict'))
    return {'status': _str(verdict.get('status')), 'reason': _str(verdict.get('reason')),
            'needed_footprint_m2': _num(verdict.get('needed_footprint_m2')),
            'shortfall_m2': _num(verdict.get('shortfall_m2'))} if verdict else None


def parse(rows, responses):
    """None when Mass took no part in the run."""
    reviews = [row for row in rows if row.get('tool') == TOOL]
    if not reviews:
        return None
    last = reviews[-1]
    response = responses.get(id(last), {})
    pattern = []
    for row in rows:
        tool, task = row.get('tool'), _str(row.get('task_id')) or ''
        if tool == LAYOUT_TOOL:
            role = 'revise' if task.endswith(REVISION) else 'propose'
        elif tool == TOOL:
            role = 're_review' if task.endswith(REVISION) else 'review'
        else:
            continue
        pattern.append({'role': role, 'owner': 'masterplan' if tool == LAYOUT_TOOL else 'mass',
                        'state': _str(row.get('state')) or 'unknown'})
    return {'status': _str(response.get('status')) or _str(last.get('state')) or 'unknown',
            'truncated': last.get('truncated') is True,
            'revised': any(p['role'] == 'revise' for p in pattern),
            'first_verdict': _verdict(responses.get(id(reviews[0]), {})),
            'verdict': _verdict(response),
            'zone_m2': _num(response.get('zone_m2')), 'gfa_target_m2': _num(response.get('gfa_target_m2')),
            'alternatives': [_alternative(a) for a in response.get('alternatives') or [] if isinstance(a, dict)],
            'pattern': pattern}
