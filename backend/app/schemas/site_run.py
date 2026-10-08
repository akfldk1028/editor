"""Product submission shape for a site run: the Orchestrator reviews a parcel (PNU), or a contiguous bundle, for a goal."""
import re
from datetime import date

# Only `limits` for now: the other Orchestrator goals need profile fields the editor does not collect yet.
SITE_GOALS = {'limits'}
# The same 19-digit rule as modules.land.pnu.normalize_pnu; schemas sit below modules in the layer
# contract (pyproject [tool.importlinter]), so the rule is restated here instead of imported.
PNU = re.compile(r'[0-9]{19}')
ISO_DATE = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}')
REQUIRED = {'goal', 'pnu'}
OPTIONAL = {'building_type', 'assessment_date', 'parcels'}
MAX_PARCELS = 50


def is_site_run(request) -> bool:
    return isinstance(request, dict) and request.get('goal') in SITE_GOALS


def validate_site_run(request):
    if not REQUIRED <= set(request) <= REQUIRED | OPTIONAL:
        raise ValueError('A site run takes goal and pnu, optionally building_type, assessment_date and parcels')
    if not isinstance(request['pnu'], str) or not PNU.fullmatch(request['pnu']):
        raise ValueError('PNU requires 19 digits')
    building_type = request.get('building_type', 'x')
    if not isinstance(building_type, str) or not 1 <= len(building_type) <= 64:
        raise ValueError('building_type must be a short string')
    if 'assessment_date' in request:
        _validate_assessment_date(request['assessment_date'])
    if 'parcels' in request:
        _validate_parcels(request['parcels'], request['pnu'])


def _validate_assessment_date(value):
    """Strict `YYYY-MM-DD` naming a real calendar date (Program and the 지구단위 review read it)."""
    if not isinstance(value, str) or not ISO_DATE.fullmatch(value):
        raise ValueError('assessment_date must be YYYY-MM-DD')
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ValueError('assessment_date must be a real date') from None


def _validate_parcels(parcels, pnu):
    """The bundle the Orchestrator asks Site to merge: 1..50 unique PNUs led by `pnu`."""
    if not isinstance(parcels, list) or not 1 <= len(parcels) <= MAX_PARCELS:
        raise ValueError(f'parcels takes 1 to {MAX_PARCELS} PNUs')
    if not all(isinstance(item, str) and PNU.fullmatch(item) for item in parcels):
        raise ValueError('Every parcel requires 19 digits')
    if len(set(parcels)) != len(parcels):
        raise ValueError('parcels must be unique')
    if parcels[0] != pnu:
        raise ValueError('parcels[0] must be the pnu')
