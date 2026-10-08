"""Product submission shape for a site run: the Orchestrator reviews one parcel (PNU) for a goal."""
import re

# Only `limits` for now: the other Orchestrator goals need profile fields the editor does not collect yet.
SITE_GOALS = {'limits'}
# The same 19-digit rule as modules.land.pnu.normalize_pnu; schemas sit below modules in the layer
# contract (pyproject [tool.importlinter]), so the rule is restated here instead of imported.
PNU = re.compile(r'[0-9]{19}')


def is_site_run(request) -> bool:
    return isinstance(request, dict) and request.get('goal') in SITE_GOALS


def validate_site_run(request):
    if not {'goal', 'pnu'} <= set(request) <= {'goal', 'pnu', 'building_type'}:
        raise ValueError('A site run takes goal and pnu, optionally building_type')
    if not isinstance(request['pnu'], str) or not PNU.fullmatch(request['pnu']):
        raise ValueError('PNU requires 19 digits')
    building_type = request.get('building_type', 'x')
    if not isinstance(building_type, str) or not 1 <= len(building_type) <= 64:
        raise ValueError('building_type must be a short string')
