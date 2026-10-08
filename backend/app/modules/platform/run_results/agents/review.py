"""The Revision Agent's answer (`revision_triage`): its verdict and the rationale every other parser reads findings from."""
from backend.app.modules.platform.run_results.common import _dict, _str, _strings

TOOL = 'revision_triage'
AGENT = 'revision'


def parse_rationale(response):
    out = []
    for item in response.get('rationale') or []:
        item = _dict(item)
        out.append({'finding': _str(item.get('finding')), 'raised_by': _str(item.get('raised_by')),
                    'category': _str(item.get('category')), 'recommended_action': _str(item.get('recommended_action')),
                    'recommended_agents': _strings(item.get('recommended_agents')),
                    'evidence': item.get('evidence') if isinstance(item.get('evidence'), (list, dict)) else None})
    return out


def parse(row, response, rationale):
    if row is None:
        return None
    return {'status': _str(response.get('status')) or _str(row.get('state')) or 'unknown', 'code': _str(response.get('code')),
            'missing_evidence': _strings(response.get('missing_evidence')), 'actions': rationale}

