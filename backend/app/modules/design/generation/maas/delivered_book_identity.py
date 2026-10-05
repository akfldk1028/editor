"""Tracked BOOK delivery helper extracted unchanged from the legacy owner tools.

No registry discovery, jury scheduling, or runtime CLI import belongs here.
"""
import json


def shape_id(source) -> str:
    """The identity of what the renderer draws, as a short hash.

    A score belongs to a picture. When the engine changes, a seat's picture
    can change while its name and its ledger score do not, and an anchor
    whose picture changed is not an anchor: three anchors carried deltas
    spread 1.32 apart because the top seat had been redrawn under a
    regulating snap, the ruler refused to move, and a whole round was
    recorded raw - unchanged pictures fell 0.4 to 1.0 with no contest.

    Geometry, not pixels: the tile label and caption are outside it, and so
    is the renderer's own code. Every field the renderer reads is inside.
    """

    import hashlib
    from dataclasses import fields, is_dataclass

    def canonical(value):
        if hasattr(value, 'geom_type'):
            # Includes interior rings; coordinate order is normalised, not rounded.
            return value.normalize().wkb_hex
        if is_dataclass(value):
            return {'type': f'{type(value).__module__}.{type(value).__qualname__}',
                    'fields': {f.name: canonical(getattr(value, f.name)) for f in fields(value)}}
        if hasattr(value, 'signature'):
            return canonical(value.signature())
        if isinstance(value, dict):
            return {str(k): canonical(v) for k, v in sorted(value.items())}
        if isinstance(value, (list, tuple)):
            return [canonical(v) for v in value]
        return value

    meta = source.metadata or {}
    payload = {'schema': 2, 'volumes': canonical(source.volumes),
               'surfaces': canonical(getattr(source, 'surfaces', ())),
               'metadata': {k: canonical(meta.get(k)) for k in
                            ('authored_height_m', 'datum_m', 'structural_bands')}}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:20]


def certificate_digest(cert):
    """The existing name-bound certificate digest, before adding its own ID."""
    import hashlib
    payload = {key: value for key, value in cert.items() if key != 'certificate_id'}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:20]


def seat_certificate(name, source, book, site, *, book_entry=None):
    """Numeric evidence and exact source identity, shared by all delivery views.

    BOOK retains its imported floor-area certificate (not a new count at the
    parcel's default storey). Projection is always measured on delivered solids.
    """
    from shapely.ops import unary_union
    ground = float(unary_union([v.footprint for v in source.volumes]).area)
    storey = None
    floor_count = None
    if name.startswith('book:'):
        if book_entry is None:
            raise ValueError('explicit BOOK entry required')
        entry = book_entry
        gross = float(entry.get('floor_area_m2') or 0)
        if gross <= 0:
            raise ValueError(f'{name}: missing BOOK floor-area certificate')
        from backend.app.modules.design.generation.maas.delivered_book_floors import delivered_floor_evidence
        retained = entry.get('delivered_floor_evidence')
        if not retained:
            raise ValueError(f'{name}: missing BOOK floor-area measurement evidence')
        fresh = delivered_floor_evidence(source, source.metadata.get('book_original_storey_evidence') or {},
                    floor_count=entry.get('book_floor_count'),
                    storey_m=entry.get('original_book_storey_height_m'))
        if (retained != fresh or not fresh['measurement_consistent']
                or gross != fresh['actual_gfa_m2']
                or source.metadata.get('book_delivered_floor_evidence') != fresh):
            raise ValueError(f'{name}: BOOK floor-area measurement evidence does not match delivered geometry')
        storey = entry.get('book_storey_height_m') or source.metadata.get('book_storey_height_m')
        floor_count = entry.get('book_floor_count') or source.metadata.get('book_floor_count')
        basis = fresh['basis']
    else:
        from backend.app.modules.design.generation.maas.massv2.measure import gross_floor_area_m2
        record = book.get(name.split('~')[0].split('^')[0]) or {}
        storey = float(source.metadata.get('authored_floor_height_m') or record.get('floor_height_m') or site.floor_height_m)
        gross = gross_floor_area_m2(source, floor_height_m=storey)
        basis = 'delivered geometry at authored storey height'
    parcel = float(site.parcel_area_m2)
    from backend.app.modules.design.generation.maas.massv2.parcel_policy import storey_limit_evidence
    storey_gate = storey_limit_evidence(source, site, storey_m=storey,
                    book_floor_count=floor_count, source_kind='book' if name.startswith('book:') else 'authored')
    if not storey_gate['satisfied']:
        raise ValueError(f"{name}: parcel storey gate: {', '.join(storey_gate['reasons'])}")
    from backend.app.modules.design.generation.maas.massv2.parcel_policy import area_limit_evidence
    area_gate = area_limit_evidence(source, site, gross)
    if not area_gate['satisfied']:
        raise ValueError(f"{name}: parcel area gate: {', '.join(area_gate['reasons'])}")
    ground = area_gate['ground_m2']
    cert = {'name': name, 'shape_id': shape_id(source), 'site_pnu': getattr(site, 'pnu', None), 'ground_m2': ground,
            'gross_m2': gross, 'storey_m': storey, 'floor_area_basis': basis,
            'coverage_pct': ground / parcel * 100, 'far_pct': gross / parcel * 100,
            'height_m': float(source.metadata.get('authored_height_m') or 0),
            'storey_limit': storey_gate, 'area_limits': area_gate}
    if name.startswith('book:'):
        cert['delivered_floor_evidence'] = fresh
    from backend.app.modules.design.generation.maas.massv2.structure import assess_standing
    from backend.app.modules.design.generation.maas.massv2.render_mesh import is_mesh_authoritative
    standing = assess_standing(source, height_m=cert['height_m'])
    if is_mesh_authoritative(source) and not standing.stands:
        raise ValueError(f"{name}: mesh gravity screen: {', '.join(standing.reasons)}")
    cert['structure'] = standing.evidence()
    cert['certificate_id'] = certificate_digest(cert)
    return cert
