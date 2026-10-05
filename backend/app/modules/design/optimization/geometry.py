import math

from shapely.affinity import rotate, translate
from shapely.geometry import Polygon, MultiPolygon, box
from shapely.ops import unary_union


class CandidateRejected(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def reject(code, message):
    raise CandidateRejected(code, message)


def finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def polygon(geometry, *, minimum_area=1.0):
    if geometry is None or geometry.is_empty or not geometry.is_valid or not math.isfinite(geometry.area):
        reject('invalid_geometry', 'Candidate geometry is empty or invalid')
    reduced = isinstance(geometry, MultiPolygon)
    if reduced:
        geometry = max(geometry.geoms, key=lambda part: part.area)
    if not isinstance(geometry, Polygon) or geometry.area < minimum_area:
        reject('invalid_geometry', 'Candidate has no supported polygon of sufficient area')
    return geometry, reduced


def build_additive(inputs, site):
    if (not isinstance(inputs, (list, tuple)) or len(inputs) != 29
            or any(not isinstance(gene, (list, tuple)) or len(gene) != 1
                   or not finite(gene[0]) or abs(gene[0]) > 1e6 for gene in inputs)):
        reject('invalid_genome', 'Additive genome requires 29 finite scalar genes')
    if any(inputs[index][0] <= 0 for index in range(25) if index % 5 in (2, 3)):
        reject('invalid_genome', 'Box dimensions must be positive')
    if inputs[25][0] < 1:
        reject('invalid_genome', 'Floor count must be positive')
    cx, cy = site.centroid.x, site.centroid.y
    rectangles = []
    for index in range(5):
        x, y, width, depth, angle = [inputs[index*5+offset][0] for offset in range(5)]
        rectangle = rotate(box(-width/2, -depth/2, width/2, depth/2), angle, origin=(0, 0))
        rectangles.append(translate(rectangle, xoff=cx+x, yoff=cy+y))
    combined = rotate(unary_union(rectangles), inputs[26][0], origin=(cx, cy))
    return polygon(combined)
