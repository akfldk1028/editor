"""Map display composition: cadastral classes, surveyed cover, then carriageways."""
import math
import re

from pyproj import Transformer
from shapely.geometry import Point, box, mapping, shape
from shapely.ops import clip_by_rect, transform, unary_union
from shapely.strtree import STRtree

from .sources import bbox

GROUND_CLASS = {'도': 'road', '차': 'paved', '주': 'paved', '철': 'rail',
                '공': 'green', '체': 'green', '원': 'green', '묘': 'green', '제': 'green',
                '천': 'water', '구': 'water', '유': 'water',
                '전': 'farm', '답': 'farm', '과': 'farm', '목': 'farm', '임': 'forest'}
NATURAL = ('water', 'green', 'forest', 'farm', 'bare')


def _cover(code):
    if not str(code).isdigit():
        return None
    code = int(code)
    if code in (154, 155, 622):
        return 'paved'
    if code == 153:
        return 'rail'
    return {1: 'built', 2: 'farm', 3: 'forest', 4: 'green', 5: 'green', 6: 'bare', 7: 'water'}.get(code // 100)


def normalize(source, kind, lat, lon, radius):
    to_m = Transformer.from_crs(4326, 5186, always_xy=True).transform
    center = Point(*to_m(lon, lat))
    bounds = bbox(lat, lon, radius)
    result = []
    for row in source['rows']:
        p = row['properties']
        label = _cover(p.get('l3_code')) if kind != 'cadastre' else None
        # Built-up fill is never drawn or used by either composition index.
        # Preserve the raw source receipt, but avoid constructing and clipping
        # thousands of polygons that composition would immediately discard.
        if kind != 'cadastre' and label in (None, 'built'):
            continue
        original = shape(row['geometry'])
        geometry = clip_by_rect(original, *bounds).buffer(0)
        if geometry.is_empty or transform(to_m, geometry).distance(center) > radius:
            continue
        if kind == 'cadastre':
            match = re.search(r'([가-힣])\s*$', p.get('jibun') or '')
            jimok = match.group(1) if match else None
            props = {'pnu': p.get('pnu'), 'jimok': jimok,
                     'ground': GROUND_CLASS.get(jimok, 'lot' if jimok else 'unknown'),
                     # Clip the original boundary, not the boundary of the clip.
                     # Real edges coincident with the request bbox remain valid.
                     'parcel_boundary': mapping(original.boundary.intersection(box(*bounds)))}
        else:
            props = {'cover': label, 'l3_code': p.get('l3_code'), 'l3_name': p.get('l3_name')}
        result.append({'type': 'Feature', 'geometry': mapping(geometry), 'properties': props})
    return result


class Index:
    def __init__(self, features, keep, label=lambda p: None):
        pairs = [(shape(f['geometry']).buffer(0), f['properties']) for f in features if keep(f['properties'])]
        pairs = [(g, p) for g, p in pairs if not g.is_empty]
        self.parts = [g for g, _ in pairs]
        self.labels = [label(p) for _, p in pairs]
        self.tree = STRtree(self.parts)

    def near(self, geometry):
        return [(self.parts[i], self.labels[i]) for i in self.tree.query(geometry)]


def _polygons(geometry):
    return [g for g in getattr(geometry, 'geoms', [geometry])
            if g.geom_type in ('Polygon', 'MultiPolygon') and not g.is_empty]


def _pieces(geometry, index, threshold):
    parts = {}
    m2 = 111320.0 ** 2 * math.cos(math.radians(geometry.centroid.y))
    for part, label in index.near(geometry):
        polygons = [p for p in _polygons(part.intersection(geometry)) if p.area * m2 >= threshold]
        if polygons:
            parts.setdefault(label, []).extend(polygons)
    return {label: unary_union(items) for label, items in parts.items()}


def compose(parcels, covers, roads, *, parcels_available=True):
    if parcels:
        bounds = [shape(f['geometry']).bounds for f in parcels]
        envelope = box(min(b[0] for b in bounds), min(b[1] for b in bounds),
                       max(b[2] for b in bounds), max(b[3] for b in bounds))
        # WFS returns whole regional polygons. Nothing outside all parcel bounds
        # can contribute, so cut once before hundreds of parcel intersections.
        covers = [{**f, 'geometry': mapping(shape(f['geometry']).buffer(0).intersection(envelope))} for f in covers]
        covers = [f for f in covers if not shape(f['geometry']).is_empty]
    natural = Index(covers, lambda p: p['cover'] in NATURAL, lambda p: p['cover'])
    built_roads = Index(covers, lambda p: str(p.get('l3_code')) == '154', lambda p: 'road')
    features, split, road_parts = [], 0, []
    for feature in parcels:
        p = feature['properties']
        base = {'layer': 'ground', 'ground': p['ground'], 'jimok': p['jimok'], 'id': p['pnu']}
        if 'parcel_boundary' in p:
            base['parcel_boundary'] = p['parcel_boundary']
            base['parcel_boundary_id'] = p['pnu']
        road_parcel = p['ground'] in ('road', 'rail')
        geometry = shape(feature['geometry']).buffer(0)
        parts = (_pieces(geometry, natural, 20) if road_parcel else
                 _pieces(geometry, built_roads, 200) if p['ground'] in ('lot', 'unknown', None) else {})
        if not parts:
            features.append({'type': 'Feature', 'geometry': feature['geometry'], 'properties': base})
            continue
        rest = geometry.difference(unary_union(list(parts.values())))
        if rest.area > 0:
            features.append({'type': 'Feature', 'geometry': mapping(rest), 'properties': base})
        if not road_parcel and 'road' in parts:
            road_parts.append(parts['road'])
        for label, part in parts.items():
            features.append({'type': 'Feature', 'geometry': mapping(part), 'properties': {
                **base, 'ground': label, 'id': f"{p['pnu']}:{label}", 'within': p['ground'],
                'method': f"EGIS:lv3_2025y land cover inside a {'road parcel' if road_parcel else 'lot'}"}})
        split += 1
    lots = Index(parcels, lambda p: p['ground'] not in ('road', 'rail'))
    drawn_road = unary_union(road_parts) if road_parts else None
    count = 0
    for feature in covers:
        p = feature['properties']
        if p['cover'] == 'built':
            continue
        geometry = shape(feature['geometry']).buffer(0)
        parts = ([geometry] if not parcels_available else
                 [piece for lot, _ in lots.near(geometry) for piece in _polygons(lot.intersection(geometry))])
        if not parts:
            continue
        piece = unary_union(parts)
        if drawn_road is not None:
            piece = piece.difference(drawn_road)
        if piece.is_empty or not piece.area:
            continue
        features.append({'type': 'Feature', 'geometry': mapping(piece), 'properties': {'layer': 'cover', **p}})
        count += 1
    features.extend((roads.get('features') or {}).get('features') or [])
    return {'type': 'FeatureCollection', 'features': features}, {
        'parcels': len(parcels), 'cover': count, 'parcels_split_by_cover': split,
        'carriageways': (roads.get('counts') or {}).get('carriageways', 0)}
