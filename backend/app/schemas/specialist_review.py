"""Product submission shape for the owner's existing read-only review template."""
import json


REVIEW_TOOLS = {
    'systems': {'systems_review', 'systems_ifc_review', 'systems_clearance', 'systems_requirements', 'systems_analyze'},
    'domain_expert': {'domain_review'},
    'interior': {'interior_review'},
}


def validate_specialist_review(request):
    if set(request) != {'goal', 'specialist_reviews'} or request.get('goal') != 'specialist_review':
        raise ValueError('Only health and read-only specialist review templates are supported')
    items = request['specialist_reviews']
    if not isinstance(items, list) or not 1 <= len(items) <= 6:
        raise ValueError('One to six explicit specialist reviews are required')
    seen = set()
    for item in items:
        if not isinstance(item, dict) or set(item) != {'agent', 'tool', 'args', 'source_versions'}:
            raise ValueError('Invalid specialist review fields')
        agent, tool = item['agent'], item['tool']
        if (not isinstance(agent, str) or not isinstance(tool, str)
                or tool not in REVIEW_TOOLS.get(agent, set()) or tool in seen):
            raise ValueError('Unsupported or duplicate specialist tool')
        seen.add(tool)
        if not isinstance(item['args'], dict):
            raise ValueError('Specialist args must be an object')
        try:
            json.dumps(item['args'], allow_nan=False)
        except (TypeError, ValueError):
            raise ValueError('Specialist args must be finite JSON') from None
        versions = item['source_versions']
        if (not isinstance(versions, dict) or not versions
                or any(not isinstance(key, str) or type(value) is not int or value < 1
                       for key, value in versions.items())):
            raise ValueError('Specialist sources require positive revisions')


def specialist_items(request):
    return request['specialist_reviews'] if request.get('goal') == 'specialist_review' else []
