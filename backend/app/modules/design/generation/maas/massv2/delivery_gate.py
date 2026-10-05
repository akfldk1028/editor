"""Shared eligibility of a delivered authored mass; geometry owners stay separate."""
from dataclasses import dataclass, replace

STATURE_UPPER_RATIO = 5.0 / 3.0
STATURE_LOWER_RATIO = 2.0 / 3.0
STATURE_ROUNDING_TOLERANCE_M = 0.01


def stature_ceiling_m(declared_storeys, storey_m):
    return STATURE_UPPER_RATIO * declared_storeys * storey_m


def stature_evidence(source, *, storey_m, declaration=None):
    declaration = source.metadata if declaration is None else declaration
    declared = float(declaration.get('declared_storeys') or 0.)
    body = source.body_height_m()
    if body <= 0.:
        spans = [max(0., float(v.top_fraction) - float(v.bottom_fraction)) for v in source.volumes]
        body = float(source.metadata.get('authored_height_m') or 0.) * (max(spans) if spans else 1.)
    over = (declared > 0. and bool(declaration.get('stature_is_building'))
            and body > stature_ceiling_m(declared, storey_m) + STATURE_ROUNDING_TOLERANCE_M)
    short = declared > 0. and body < STATURE_LOWER_RATIO * declared * storey_m
    return {'declared_storeys': declared, 'delivered_body_m': round(body, 2),
            'crushed': bool(short or over), 'over': bool(over)}


def stamp_authored_composition(form, *, storey_m):
    """Freeze unclipped authorship before schedule, variants, fitting or growth.

    Clipping an oversized seed can remove its connecting body; fitting may
    later restore it. Such a clipped fragment is not the author's baseline.
    Delivery retains its independent legal clip and preservation checks.
    """
    from backend.app.modules.design.generation.maas.massv2.compile import compile_matrix_form
    from backend.app.modules.design.generation.maas.massv2 import composition
    source = compile_matrix_form(form, storey_height_m=storey_m, allowed_at=None)
    if source is None:
        return form
    return replace(form, extra={**dict(form.extra),
        'authored_composition': composition.band_id(composition.read(source))})


@dataclass(frozen=True)
class DeliveryAssessment:
    plausibility: object
    composition: object
    stature: dict
    composition_kept: bool
    reasons: tuple
    legal_storeys: dict
    legal_area: dict
    gap: dict

    @property
    def accepted(self):
        return not self.reasons

    def evidence(self):
        return {'accepted': self.accepted, 'reasons': list(self.reasons),
                'plausibility': self.plausibility.evidence(), 'stature': self.stature,
                'composition_kept': self.composition_kept,
                'composition': self.composition.to_dict(),
                'legal_storeys': self.legal_storeys, 'legal_area': self.legal_area,
                'gap': self.gap}


def assess_delivery(source, site, *, storey_m=None, declaration=None, parcel_area_m2=None):
    from backend.app.modules.design.generation.maas.massv2 import plausibility, composition
    from backend.app.modules.design.generation.maas.massv2.parcel_policy import storey_limit_evidence, area_limit_evidence
    from backend.app.modules.design.generation.maas.massv2.measure import gross_floor_area_m2
    from backend.app.modules.design.generation.maas.massv2.ablation import gap_evidence
    storey_m = float(storey_m or source.metadata.get('authored_floor_height_m') or site.floor_height_m)
    declaration = source.metadata if declaration is None else declaration
    physical = plausibility.assess(source,
        parcel_area_m2=(site.parcel_area_m2 if parcel_area_m2 is None else parcel_area_m2),
        max_slenderness=plausibility.slenderness_limit(
            far_capacity_m2=site.far_capacity_m2, ground_capacity_m2=site.ground_capacity_m2),
        floor_height_m=storey_m)
    reading = composition.read(source)
    expected = declaration.get('authored_composition')
    kept = expected is None or expected == composition.band_id(reading)
    stature = stature_evidence(source, storey_m=storey_m, declaration=declaration)
    reasons = list(physical.reasons)
    if not physical.occupiable and not reasons:
        reasons.append('not_occupiable')
    if stature['crushed']:
        reasons.append('declared_stature_over' if stature['over'] else 'declared_stature_short')
    if not kept:
        reasons.append('authored_composition_changed')
    gap = gap_evidence(source, declaration=declaration)
    if not gap['satisfied']:
        reasons.append('declared_gap_closed')
    # Fitting precedes final regulation/realignment. Certify the source that
    # will actually be paired, using the same final-source owners as delivery.
    storeys = storey_limit_evidence(source, site, storey_m=storey_m,
                                   declared_storeys=declaration.get('declared_storeys'))
    areas = area_limit_evidence(source, site, gross_floor_area_m2(source, floor_height_m=storey_m))
    reasons.extend(storeys['reasons'])
    reasons.extend(areas['reasons'])
    return DeliveryAssessment(physical, reading, stature, kept, tuple(reasons), storeys, areas, gap)
