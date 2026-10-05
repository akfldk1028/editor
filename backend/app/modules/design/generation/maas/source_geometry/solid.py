"""Height-bounded solids: extensible surfaces and one curved sampling policy.

Surface coordinates are authored coordinates, independent of the clipped plan.
Curves are piecewise-linear approximations on a deterministic plan mesh; they
are not an exact B-rep or an engineering tolerance certificate. Existing flat
and one-axis sections continue to use analytic slices in ``ir.SourceVolume``.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import math
from typing import Protocol

from shapely import affinity, get_precision
from shapely.geometry import LineString, Polygon, box
from shapely.ops import split, triangulate, unary_union


# One policy for section, volume and rendered curved faces. It bounds mesh
# density, not approximation error; narrow authored features need finer input.
CURVE_GRID_DIVISIONS = 24
CURVE_MINIMUM_STEP_M = 0.5
GEOMETRY_EPSILON = 1e-9


class HeightSurface(Protocol):
    """Share of the owner's vertical band at an authored plan coordinate.

    Implementations must be immutable, finite, deterministic and serializable.
    ``break_lines`` lists discontinuities of derivative needing exact vertices.
    A new implementation needs no shape branch in any solid consumer.
    """
    def value(self, x: float, y: float) -> float: ...
    def break_lines(self) -> tuple[tuple[float, float, float], ...]: ...
    def signature(self) -> dict: ...


@dataclass(frozen=True)
class ConstantSurface:
    height: float

    def __post_init__(self):
        if not math.isfinite(self.height):
            raise ValueError("surface height must be finite")

    def value(self, x, y):
        return self.height

    def break_lines(self):
        return ()

    def signature(self):
        return {"type": "constant", "height": self.height}


@dataclass(frozen=True)
class PolynomialSurface:
    """Authored polynomial height: (x exponent, y exponent, coefficient).

    Coordinates are explicit, commonly the unit plan of a Placement. This
    supports tilted ground, saddles, valleys and independent undersides without
    requiring a new tuple tag. Use AffineSurface when moving the surface.
    """
    terms: tuple[tuple[int, int, float], ...]

    def __post_init__(self):
        if any(i < 0 or j < 0 or not isinstance(i, int) or not isinstance(j, int)
               or not math.isfinite(c) for i, j, c in self.terms):
            raise ValueError("polynomial terms require nonnegative integer powers and finite coefficients")

    def value(self, x, y):
        return sum(c * x ** i * y ** j for i, j, c in self.terms)

    def break_lines(self):
        return ()

    def signature(self):
        return {"type": "polynomial", "terms": self.terms}


@dataclass(frozen=True)
class ProfileSurface:
    points: tuple[tuple[float, float], ...]
    axis: tuple[float, float]
    span: tuple[float, float]

    def value(self, x, y):
        from backend.app.modules.design.generation.maas.source_geometry.ir import profile_height
        lo, hi = self.span
        u = (x * self.axis[0] + y * self.axis[1] - lo) / max(hi - lo, 1e-9)
        return profile_height(self.points, min(1.0, max(0.0, u)))

    def break_lines(self):
        lo, hi = self.span
        return tuple((*self.axis, lo + u * (hi - lo)) for u, _ in self.points)

    def signature(self):
        return {"type": "profile", "points": self.points, "axis": self.axis, "span": self.span}


@dataclass(frozen=True)
class AffineSurface:
    """Pull back a surface by a world-to-authored 2D affine map.

    Map order follows Shapely: (a, b, d, e, xoff, yoff). Heights can also be
    renormalized when a compiler emits a sub-band of the authored vertical span.
    """
    surface: HeightSurface
    world_to_authored: tuple[float, float, float, float, float, float]
    scale: float = 1.0
    offset: float = 0.0

    def value(self, x, y):
        a, b, d, e, xo, yo = self.world_to_authored
        return self.offset + self.scale * self.surface.value(a*x + b*y + xo, d*x + e*y + yo)

    def break_lines(self):
        a, b, d, e, xo, yo = self.world_to_authored
        return tuple((px*a + py*d, px*b + py*e, c-px*xo-py*yo)
                     for px, py, c in self.surface.break_lines())

    def signature(self):
        return {"type": "affine", "surface": self.surface.signature(),
                "world_to_authored": self.world_to_authored, "scale": self.scale, "offset": self.offset}


def inverse_plan_affine(matrix):
    a, b, d, e, xo, yo = matrix
    det = a*e-b*d
    if abs(det) <= GEOMETRY_EPSILON:
        raise ValueError("solid surface requires an invertible plan transform")
    return (e/det, -b/det, -d/det, a/det, (b*yo-e*xo)/det, (d*xo-a*yo)/det)


def surface_from_record(record, _depth=0):
    """Validated data-only import. Unknown kinds fail; no executable payloads."""
    if not isinstance(record, dict) or _depth > 8:
        raise ValueError("surface must be a bounded typed record")
    kind = record.get("type")
    try:
        if kind == "constant":
            return ConstantSurface(float(record["height"]))
        if kind == "polynomial":
            terms = tuple(tuple(t) for t in record["terms"])
            if not 1 <= len(terms) <= 64 or any(len(t) != 3 or t[0] > 6 or t[1] > 6 for t in terms):
                raise ValueError("polynomial payload supports at most 64 terms, degree at most six per axis")
            return PolynomialSurface(terms)
        if kind == "profile":
            points = tuple((float(u),float(h)) for u,h in record["points"])
            axis, span = tuple(record["axis"]), tuple(record["span"])
            if (len(axis) != 2 or len(span) != 2 or span[1] <= span[0]
                    or len(points) < 2 or len(points) > 256
                    or any(a[0] >= b[0] for a,b in zip(points,points[1:]))
                    or any(not math.isfinite(n) for p in points for n in p)
                    or any(not math.isfinite(n) for n in axis+span)):
                raise ValueError("invalid ordered profile surface")
            return ProfileSurface(points,axis,span)
        if kind == "affine":
            matrix = tuple(float(n) for n in record["world_to_authored"])
            if len(matrix) != 6 or not all(math.isfinite(n) for n in matrix):
                raise ValueError("surface affine must contain six finite coefficients")
            inverse_plan_affine(matrix)
            scale, offset = float(record.get("scale",1)), float(record.get("offset",0))
            if not math.isfinite(scale) or not math.isfinite(offset):
                raise ValueError("surface height transform must be finite")
            return AffineSurface(surface_from_record(record["surface"],_depth+1),matrix,scale,offset)
    except (KeyError, TypeError, OverflowError) as exc:
        raise ValueError("malformed surface record") from exc
    raise ValueError(f"unsupported surface type: {kind!r}")


def surface_bounds(surface, bounds):
    """Conservative value bounds; polynomial Bernstein control hull is bounded.

    Used for payload admission so a roof cannot silently escape its legal band
    between samples. A conservative hull can reject a valid elaborate surface;
    split that authored patch rather than quietly accepting uncertain bounds.
    """
    if isinstance(surface, ConstantSurface):
        return surface.height,surface.height
    if isinstance(surface, ProfileSurface):
        return min(h for _,h in surface.points),max(h for _,h in surface.points)
    if isinstance(surface, AffineSurface):
        domain = affinity.affine_transform(box(*bounds),surface.world_to_authored)
        low,high = surface_bounds(surface.surface,domain.bounds)
        values = (surface.offset+surface.scale*low,surface.offset+surface.scale*high)
        return min(values),max(values)
    if not isinstance(surface, PolynomialSurface):
        raise ValueError("external surface requires a supported bounded record")
    x0,y0,x1,y1 = bounds
    # A separable quadratic - every term in x alone or y alone, degree at most
    # two - has an exact extremum on a box: each axis at its ends or at its
    # own vertex. The Bernstein hull below overestimates such an interior peak
    # by half its rise, and refused a dome whose true peak was exactly the
    # band top. Exact is still conservative in the sense this check needs.
    if surface.terms and all((i == 0 or j == 0) and i <= 2 and j <= 2 for i,j,_ in surface.terms):
        def axis_extremes(coefficients, lo, hi):
            a = coefficients.get(0,0.0); b = coefficients.get(1,0.0); c = coefficients.get(2,0.0)
            values = [a + b*t + c*t*t for t in (lo,hi)]
            if c != 0:
                vertex = -b/(2*c)
                if lo < vertex < hi:
                    values.append(a + b*vertex + c*vertex*vertex)
            return min(values), max(values)
        constant = sum(c for i,j,c in surface.terms if i == 0 and j == 0)
        fx = {}; fy = {}
        for i,j,c in surface.terms:
            if i > 0: fx[i] = fx.get(i,0.0) + c
            elif j > 0: fy[j] = fy.get(j,0.0) + c
        x_low,x_high = axis_extremes(fx,x0,x1)
        y_low,y_high = axis_extremes(fy,y0,y1)
        return constant + x_low + y_low, constant + x_high + y_high
    coefficients = {}
    for i,j,c in surface.terms:
        for k in range(i+1):
            for l in range(j+1):
                coefficients[k,l] = coefficients.get((k,l),0)+c*math.comb(i,k)*math.comb(j,l)*x0**(i-k)*y0**(j-l)*(x1-x0)**k*(y1-y0)**l
    n = max((i for i,j in coefficients),default=0)
    m = max((j for i,j in coefficients),default=0)
    control = [sum(c*math.comb(i,k)/math.comb(n,k)*math.comb(j,l)/math.comb(m,l)
                   for (k,l),c in coefficients.items() if k <= i and l <= j)
               for i in range(n+1) for j in range(m+1)]
    return min(control),max(control)


def thickness_bounds(top, bottom, bounds):
    """Conservative separation proof, including a following plate underside."""
    def core(surface):
        if isinstance(surface,AffineSurface):
            base = (surface.surface if surface.world_to_authored == (1,0,0,1,0,0)
                    else AffineSurface(surface.surface,surface.world_to_authored))
            return base,surface.scale,surface.offset
        return surface,1,0
    a,scale_a,offset_a = core(top)
    b,scale_b,offset_b = core(bottom)
    if a.signature() == b.signature():
        low,high = surface_bounds(a,bounds)
        values = [(scale_a-scale_b)*v+offset_a-offset_b for v in (low,high)]
        return min(values),max(values)
    top_low,top_high = surface_bounds(top,bounds)
    bottom_low,bottom_high = surface_bounds(bottom,bounds)
    return top_low-bottom_high,top_high-bottom_low


def polygons(shape):
    if shape is None or shape.is_empty:
        return []
    if isinstance(shape, Polygon):
        return [shape]
    return [p for g in getattr(shape, "geoms", ()) for p in polygons(g)]


def _triangles(shape):
    """Triangulate with holes, clipping Delaunay triangles to the true region."""
    for part in polygons(shape):
        for candidate in triangulate(part):
            for cut in polygons(candidate.intersection(part)):
                if cut.area <= GEOMETRY_EPSILON:
                    continue
                if len(cut.exterior.coords) == 4 and not cut.interiors:
                    yield tuple(cut.exterior.coords)[:3]
                else:
                    # The intersection may add concave boundary vertices.
                    for triangle in triangulate(cut):
                        if cut.covers(triangle):
                            yield tuple(triangle.exterior.coords)[:3]


# Cache only immutable triangle tuples under exact geometry/precision inputs.
# Bound retained derived data independently of the geometric sampling policy.
# Sixteen entries thrashed: a 35-volume mass under the legal fit's fourteen-step
# imposed scan asked for thousands of distinct meshes per sentence and rebuilt
# 2,320 of 5,053 requests (392 s of a 470 s silence gate, 7.7 million shapely
# objects). Meshes are small tuples; two thousand of them is a few megabytes.
_PLAN_MESH_CACHE_LIMIT = 2048
_PLAN_MESH_CACHE = OrderedDict()


def plan_mesh(region, domain, *, curved, break_lines=()):
    break_lines = tuple(tuple(line) for line in break_lines)
    key = (region.wkb, domain.wkb, float(get_precision(region)),
           float(get_precision(domain)), curved, break_lines,
           CURVE_GRID_DIVISIONS, CURVE_MINIMUM_STEP_M, GEOMETRY_EPSILON)
    cached = _PLAN_MESH_CACHE.pop(key, None)
    if cached is not None:
        _PLAN_MESH_CACHE[key] = cached
        return cached
    result = _uncached_plan_mesh(region, domain, curved=curved, break_lines=break_lines)
    _PLAN_MESH_CACHE[key] = result
    if len(_PLAN_MESH_CACHE) > _PLAN_MESH_CACHE_LIMIT:
        _PLAN_MESH_CACHE.popitem(last=False)
    return result


def _uncached_plan_mesh(region, domain, *, curved, break_lines=()):
    """Triangles retaining plan holes and every declared fold line."""
    regions = [region]
    minx, miny, maxx, maxy = domain.bounds
    if curved:
        step = max(CURVE_MINIMUM_STEP_M, max(maxx-minx, maxy-miny) / CURVE_GRID_DIVISIONS)
        nx = max(1, math.ceil((maxx-minx)/step))
        ny = max(1, math.ceil((maxy-miny)/step))
        regions = [region.intersection(box(minx+i*step, miny+j*step,
                                            min(maxx, minx+(i+1)*step), min(maxy, miny+(j+1)*step)))
                   for i in range(nx) for j in range(ny)]
    reach = math.hypot(maxx-minx, maxy-miny) * 3 + 1
    cx, cy = (minx+maxx)/2, (miny+maxy)/2
    for px, py, offset in break_lines:
        norm = px*px+py*py
        if norm < GEOMETRY_EPSILON:
            continue
        t = (offset-px*cx-py*cy)/norm
        bx, by = cx+t*px, cy+t*py
        length = math.sqrt(norm)
        line = LineString([(bx-py/length*reach, by+px/length*reach),
                           (bx+py/length*reach, by-px/length*reach)])
        regions = [p for r in regions for component in polygons(r)
                   for p in polygons(split(component, line))]
    return tuple(triangle for region in regions for triangle in _triangles(region))


def clip_values(vertices, value_index, threshold, keep_above=True):
    """Clip an attributed polygon by an affine scalar inequality."""
    out = []
    for first, second in zip(vertices, vertices[1:] + vertices[:1]):
        a, b = first[value_index]-threshold, second[value_index]-threshold
        inside_a = a >= 0 if keep_above else a <= 0
        inside_b = b >= 0 if keep_above else b <= 0
        if inside_a:
            out.append(first)
        if inside_a != inside_b and abs(a-b) > GEOMETRY_EPSILON:
            t = a/(a-b)
            out.append(tuple(v+t*(w-v) for v, w in zip(first, second)))
    return out


def sampled_slice(mesh, z, low, high):
    """Mesh records are (x,y,bottom_share,top_share); clip BOTH surfaces."""
    if high <= low:
        return None
    share = (z-low)/(high-low)
    parts = []
    for triangle in mesh:
        points = clip_values(list(triangle), 3, share)
        points = clip_values(points, 2, share, False) if points else []
        if len(points) >= 3:
            polygon = Polygon([(p[0], p[1]) for p in points])
            if polygon.area > GEOMETRY_EPSILON:
                parts.append(polygon)
    return unary_union(parts) if parts else None


def mesh_mass_properties(mesh, low, high):
    """Exact integrals of piecewise-linear vertical columns; returns V,Mx,My,Mz."""
    total = sx = sy = sz = 0.0
    for triangle in mesh:
        # Remove inverted columns before integrating; never count negative mass.
        values = [(*v, v[3]-v[2]) for v in triangle]
        values = clip_values(values, 4, 0)
        for i in range(1, len(values)-1):
            points = [values[0], values[i], values[i+1]]
            area = Polygon([(p[0], p[1]) for p in points]).area
            bs = [low+(high-low)*p[2] for p in points]
            ts = [low+(high-low)*p[3] for p in points]
            ds = [t-b for t,b in zip(ts,bs)]
            mass = area*sum(ds)/3
            total += mass
            # Integral of products of affine functions over a triangle.
            def product(a,b):
                return area*(sum(a)*sum(b)+sum(x*y for x,y in zip(a,b)))/12
            sx += product([p[0] for p in points], ds)
            sy += product([p[1] for p in points], ds)
            sz += (product(ts,ts)-product(bs,bs))/2
    return total,sx,sy,sz


def contact_region(first, second, first_band, second_band, tolerance=0.0):
    """Plan area where two occupied vertical intervals meet within tolerance.

    This checks material, including following undersides. It does not infer a
    bearing just because the conservative band prisms overlap.
    """
    region = first.footprint.buffer(tolerance).intersection(second.footprint)
    if region.is_empty:
        return None
    if first.section_kind() == second.section_kind() == "flat":
        return region if min(first_band[1], second_band[1]) >= max(first_band[0], second_band[0])-tolerance else None
    domain = unary_union([first.authored_domain or first.footprint,
                          second.authored_domain or second.footprint]).envelope
    triangles = plan_mesh(region, domain, curved=True,
                          break_lines=first.creases()+second.creases())
    parts = []
    for triangle in triangles:
        values = [(x,y,first.top_z(x,y,*first_band)-second.bottom_z(x,y,*second_band)+tolerance,
                   second.top_z(x,y,*second_band)-first.bottom_z(x,y,*first_band)+tolerance)
                  for x,y in triangle]
        values = clip_values(values, 2, 0)
        values = clip_values(values, 3, 0) if values else []
        if len(values) >= 3:
            part = Polygon([(p[0],p[1]) for p in values])
            if part.area > GEOMETRY_EPSILON:
                parts.append(part)
    return unary_union(parts) if parts else None


def union_mass_properties(volumes, height):
    """Material union integrals, including overlapping vertical intervals.

    Partition projected regions by membership. Within each sampled triangle,
    partition again at surface crossings so endpoint order is fixed before
    integrating the union of intervals. Flat and profiled integrals are exact;
    arbitrary surfaces follow the shared curved approximation policy.
    """
    regions = []
    for volume in volumes:
        remaining = volume.footprint
        next_regions = []
        for region,members in regions:
            shared = region.intersection(volume.footprint)
            if shared.area <= GEOMETRY_EPSILON:
                next_regions.append((region,members))
                continue
            next_regions.extend((p,members) for p in polygons(region.difference(volume.footprint)))
            next_regions.extend((p,members+(volume,)) for p in polygons(shared))
            remaining = remaining.difference(region)
        next_regions.extend((p,(volume,)) for p in polygons(remaining))
        regions = next_regions
    result = [0.0]*4
    for region,members in regions:
        if len(members) == 1:
            from dataclasses import replace
            # Reuse the cached mesh only for the identical plan object.
            # Partitioned and clipped regions retain their existing rebuild.
            v = members[0]
            if region is not v.footprint:
                v = replace(v,footprint=region)
            totals = v.mass_properties(v.bottom_fraction*height,v.top_fraction*height)
            result = [a+b for a,b in zip(result,totals)]
            continue
        domain = unary_union([v.authored_domain or v.footprint for v in members]).envelope
        lines = [line for v in members for line in v.creases()]
        for v in members:
            for surface in (v.top_surface,v.bottom_surface):
                if surface is not None:
                    lines.extend(surface.break_lines())
        mesh = plan_mesh(region,domain,curved=any(v.section_kind() in ("warp","surface") for v in members),break_lines=lines)
        for triangle in mesh:
            records = []
            for x,y in triangle:
                endpoints = []
                for v in members:
                    band = (v.bottom_fraction*height,v.top_fraction*height)
                    endpoints.extend((v.bottom_z(x,y,*band),v.top_z(x,y,*band)))
                records.append((x,y,*endpoints))
            cells = [records]
            count = len(records[0])
            # Every crossing is a linear line on this triangle. After these
            # splits each interval union has the same endpoint owners inside.
            for first in range(2,count):
                for second in range(first+1,count):
                    new_cells = []
                    for cell in cells:
                        diff = [p[first]-p[second] for p in cell]
                        if min(diff) < -GEOMETRY_EPSILON and max(diff) > GEOMETRY_EPSILON:
                            augmented = [(*p,d) for p,d in zip(cell,diff)]
                            for above in (True,False):
                                cut = clip_values(augmented,count,0,above)
                                if len(cut) >= 3:
                                    new_cells.append([p[:-1] for p in cut])
                        else:
                            new_cells.append(cell)
                    cells = new_cells
            for cell in cells:
                means = [sum(p[i] for p in cell)/len(cell) for i in range(count)]
                intervals = sorted(((i,i+1) for i in range(2,count,2)
                                    if means[i+1] >= means[i]),key=lambda pair:means[pair[0]])
                merged = []
                for bottom,top in intervals:
                    if merged and means[bottom] <= means[merged[-1][1]]:
                        if means[top] > means[merged[-1][1]]:
                            merged[-1] = (merged[-1][0],top)
                    else:
                        merged.append((bottom,top))
                for bottom,top in merged:
                    triangles = [tuple((p[0],p[1],p[bottom],p[top]) for p in (cell[0],cell[i],cell[i+1]))
                                 for i in range(1,len(cell)-1)]
                    totals = mesh_mass_properties(triangles,0,1)
                    result = [a+b for a,b in zip(result,totals)]
    return tuple(result)
