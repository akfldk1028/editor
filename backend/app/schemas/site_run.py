"""Product submission shape for a site run: the Orchestrator reviews a parcel (PNU), or a contiguous bundle, for a goal."""
import re
from datetime import date

# `limits` (법규·한계 검토), `masterplan` (배치 설계: the layout the 3D view draws, with the design intent said in
# plain words) and `mass` (매스 설계: MassAgent's own cycle on the chosen layout, which asks the person to pick one of
# its forms); the other Orchestrator goals need profile fields the editor does not collect yet.
SITE_GOALS = {'limits', 'masterplan', 'mass'}
# The goals that carry a floor area and an intent (the Orchestrator's one_of floor_area_m2/brief/program).
DESIGN_GOALS = {'masterplan', 'mass'}
# The same 19-digit rule as modules.land.pnu.normalize_pnu; schemas sit below modules in the layer
# contract (pyproject [tool.importlinter]), so the rule is restated here instead of imported.
PNU = re.compile(r'[0-9]{19}')
ISO_DATE = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}')
REQUIRED = {'goal', 'pnu'}
OPTIONAL = {'building_type', 'assessment_date', 'parcels'}
# What a 배치 설계 run adds: the floor area the person wants (the Orchestrator asks for one of floor_area_m2 / brief /
# program), the ground footprint wanted (the building-zone target the placement engine searches with; Law's coverage
# ceiling is never promoted to one) and the intent in their own words (the door turns the sentence into the intent
# owner's declaration).
# and the parking planned (total, and at most this many on the ground): without it the engine plans the legal minimum,
# which usually fits on the ground, so the layout has no basement and no ramp.
LAYOUT_OPTIONAL = {'floor_area_m2', 'footprint_m2', 'intent', 'parking_stalls', 'max_surface_stalls'}
MAX_PARCELS = 50
MAX_INTENT_CHARS = 2000


def is_site_run(request) -> bool:
    return isinstance(request, dict) and request.get('goal') in SITE_GOALS


def validate_site_run(request):
    design = request.get('goal') in DESIGN_GOALS
    allowed = REQUIRED | OPTIONAL | (LAYOUT_OPTIONAL if design else set())
    if not REQUIRED <= set(request) <= allowed:
        raise ValueError('A site run takes goal and pnu, optionally building_type, assessment_date and parcels'
                         + (' (and floor_area_m2, footprint_m2, intent for masterplan and mass)' if design else ''))
    if design:
        if not isinstance(request.get('building_type'), str) or not request['building_type'].strip():
            raise ValueError('A masterplan or mass run needs the building_type')
        area = request.get('floor_area_m2')
        if area is None or isinstance(area, bool) or not isinstance(area, (int, float)) or not 1 <= area <= 10_000_000:
            raise ValueError('A masterplan or mass run needs floor_area_m2 between 1 and 10,000,000')
        footprint = request.get('footprint_m2')
        if 'footprint_m2' in request and (isinstance(footprint, bool) or not isinstance(footprint, (int, float)) or not 1 <= footprint <= area):
            raise ValueError('footprint_m2 is the ground footprint wanted, between 1 and floor_area_m2')
        for key in ('parking_stalls', 'max_surface_stalls'):
            if key in request and (type(request[key]) is not int or not 0 <= request[key] <= 10_000):
                raise ValueError(f'{key} is a whole number of stalls (0 to 10,000)')
        if request.get('max_surface_stalls', 0) > request.get('parking_stalls', 10_001):
            raise ValueError('max_surface_stalls cannot exceed parking_stalls')
        if 'intent' in request and (not isinstance(request['intent'], str) or not 1 <= len(request['intent'].strip()) <= MAX_INTENT_CHARS):
            raise ValueError(f'intent is a sentence of at most {MAX_INTENT_CHARS} characters')
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
