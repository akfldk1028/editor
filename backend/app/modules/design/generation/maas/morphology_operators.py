"""MAAS-style morphology operators on ARR mass footprints.

These operators work on Shapely UTM polygons after ARR has already produced a
candidate mass. They are intentionally conservative: every output is expected
to go through the legal repair/evaluation pass before it is shown to users.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shapely.affinity import rotate, scale, translate
from shapely.ops import unary_union
from shapely.geometry import MultiPolygon, Polygon, box


@dataclass(frozen=True)
class MorphologyVariant:
    operator: str
    footprint: Polygon
    upper_footprint: Polygon | None = None
    lower_floor_fraction: float | None = None
    notes: tuple[str, ...] = ()
    verb_sequence: tuple[dict[str, Any], ...] = ()
    source_geometry_status: str | None = None
    source_verb_trace: tuple[dict[str, Any], ...] = ()
    source_signature: dict[str, Any] | None = None
    source_volumes: tuple[dict[str, Any], ...] = ()
    source_surfaces: tuple[dict[str, Any], ...] = ()
    research_basis: dict[str, Any] | None = None
    # Runtime-only typed authority. It is intentionally omitted from feature
    # transport and exists only long enough for final legal re-materialization.
    source_mass: Any | None = None


def largest_polygon(geometry: Polygon | MultiPolygon) -> Polygon:
    if isinstance(geometry, Polygon):
        return geometry
    polygons = [p for p in geometry.geoms if not p.is_empty]
    if not polygons:
        raise ValueError("geometry has no polygon parts")
    return max(polygons, key=lambda p: p.area)


def _clean(poly) -> Polygon | None:
    if poly is None or poly.is_empty:
        return None
    if isinstance(poly, MultiPolygon):
        poly = largest_polygon(poly)
    if not poly.is_valid:
        poly = poly.buffer(0)
        if isinstance(poly, MultiPolygon):
            poly = largest_polygon(poly)
    if poly.is_empty or poly.area < 1.0:
        return None
    return poly


def _corner_cut(base: Polygon, *, west: bool, north: bool, ratio: float) -> Polygon | None:
    minx, miny, maxx, maxy = base.bounds
    width = (maxx - minx) * ratio
    depth = (maxy - miny) * ratio
    x0 = minx if west else maxx - width
    x1 = minx + width if west else maxx
    y0 = maxy - depth if north else miny
    y1 = maxy if north else miny + depth
    return _clean(base.difference(box(x0, y0, x1, y1)))


def _edge_notch(base: Polygon, *, side: str, width_ratio: float, depth_ratio: float) -> Polygon | None:
    minx, miny, maxx, maxy = base.bounds
    width = maxx - minx
    depth = maxy - miny
    if side in ("north", "south"):
        cut_w = width * width_ratio
        x0 = minx + (width - cut_w) / 2
        x1 = x0 + cut_w
        y0, y1 = (maxy - depth * depth_ratio, maxy) if side == "north" else (miny, miny + depth * depth_ratio)
    else:
        cut_d = depth * width_ratio
        y0 = miny + (depth - cut_d) / 2
        y1 = y0 + cut_d
        x0, x1 = (minx, minx + width * depth_ratio) if side == "west" else (maxx - width * depth_ratio, maxx)
    return _clean(base.difference(box(x0, y0, x1, y1)))


def _directional_bar(base: Polygon, *, xfactor: float, yfactor: float, xshift: float, yshift: float) -> Polygon | None:
    minx, miny, maxx, maxy = base.bounds
    scaled = _clean(scale(base, xfact=xfactor, yfact=yfactor, origin="centroid"))
    if scaled is None:
        return None
    shifted = translate(scaled, xoff=(maxx - minx) * xshift, yoff=(maxy - miny) * yshift)
    return _clean(shifted.intersection(base))


def _bridged_split(base: Polygon, *, axis: str, gap_ratio: float, bridge_ratio: float) -> Polygon | None:
    """Split-like plan with a thin bridge so the mass remains one polygon."""
    minx, miny, maxx, maxy = base.bounds
    width = maxx - minx
    depth = maxy - miny
    if axis == "x":
        gap = width * gap_ratio
        bridge = depth * bridge_ratio
        x0 = (minx + maxx - gap) / 2
        x1 = x0 + gap
        lower = box(x0, miny, x1, (miny + maxy - bridge) / 2)
        upper = box(x0, (miny + maxy + bridge) / 2, x1, maxy)
        cutter = unary_union([lower, upper])
    else:
        gap = depth * gap_ratio
        bridge = width * bridge_ratio
        y0 = (miny + maxy - gap) / 2
        y1 = y0 + gap
        left = box(minx, y0, (minx + maxx - bridge) / 2, y1)
        right = box((minx + maxx + bridge) / 2, y0, maxx, y1)
        cutter = unary_union([left, right])
    return _clean(base.difference(cutter))


def _branch_plan(base: Polygon, *, angle: float, trunk_ratio: float, arm_ratio: float) -> Polygon | None:
    """Y/branch-like 2D approximation clipped inside the legal base."""
    cx, cy = base.centroid.x, base.centroid.y
    minx, miny, maxx, maxy = base.bounds
    width = maxx - minx
    depth = maxy - miny
    trunk = box(cx - width * trunk_ratio / 2, miny, cx + width * trunk_ratio / 2, maxy)
    arm_len = max(width, depth) * 0.78
    arm_w = min(width, depth) * arm_ratio
    arm = box(cx - arm_w / 2, cy - arm_len * 0.08, cx + arm_w / 2, cy + arm_len * 0.62)
    left = rotate(arm, angle, origin=(cx, cy))
    right = rotate(arm, -angle, origin=(cx, cy))
    return _clean(unary_union([trunk, left, right]).intersection(base))


def _pinch_plan(base: Polygon, *, axis: str, waist_ratio: float, depth_ratio: float) -> Polygon | None:
    minx, miny, maxx, maxy = base.bounds
    width = maxx - minx
    depth = maxy - miny
    if axis == "x":
        cut_w = width * (1.0 - waist_ratio) / 2
        cut_d = depth * depth_ratio
        y0 = miny + (depth - cut_d) / 2
        y1 = y0 + cut_d
        cutters = [box(minx, y0, minx + cut_w, y1), box(maxx - cut_w, y0, maxx, y1)]
    else:
        cut_d = depth * (1.0 - waist_ratio) / 2
        cut_w = width * depth_ratio
        x0 = minx + (width - cut_w) / 2
        x1 = x0 + cut_w
        cutters = [box(x0, miny, x1, miny + cut_d), box(x0, maxy - cut_d, x1, maxy)]
    return _clean(base.difference(unary_union(cutters)))


def _interlock_cross(base: Polygon, *, angle: float, bar_ratio: float) -> Polygon | None:
    """Interlock/overlap-like cross mass clipped to the legal base."""
    minx, miny, maxx, maxy = base.bounds
    cx, cy = base.centroid.x, base.centroid.y
    width = maxx - minx
    depth = maxy - miny
    bar_w = min(width, depth) * bar_ratio
    long = max(width, depth) * 1.28
    bar_a = box(cx - long / 2, cy - bar_w / 2, cx + long / 2, cy + bar_w / 2)
    bar_b = box(cx - bar_w / 2, cy - long / 2, cx + bar_w / 2, cy + long / 2)
    geom = unary_union([
        rotate(bar_a, angle, origin=(cx, cy)),
        rotate(bar_b, angle, origin=(cx, cy)),
    ])
    return _clean(geom.intersection(base))


def _overlap_shifted_slabs(base: Polygon, *, axis: str, slab_ratio: float, shift_ratio: float) -> Polygon | None:
    minx, miny, maxx, maxy = base.bounds
    cx, cy = base.centroid.x, base.centroid.y
    width = maxx - minx
    depth = maxy - miny
    if axis == "x":
        slab = box(cx - width * 0.36, cy - depth * slab_ratio / 2, cx + width * 0.36, cy + depth * slab_ratio / 2)
        a = translate(slab, xoff=-width * shift_ratio, yoff=-depth * 0.12)
        b = translate(slab, xoff=width * shift_ratio, yoff=depth * 0.12)
    else:
        slab = box(cx - width * slab_ratio / 2, cy - depth * 0.36, cx + width * slab_ratio / 2, cy + depth * 0.36)
        a = translate(slab, xoff=-width * 0.12, yoff=-depth * shift_ratio)
        b = translate(slab, xoff=width * 0.12, yoff=depth * shift_ratio)
    return _clean(unary_union([a, b]).intersection(base))


def _upper_diagonal_connect(base: Polygon, *, axis: str, upper_ratio: float, distance_ratio: float) -> Polygon | None:
    minx, miny, maxx, maxy = base.bounds
    width = maxx - minx
    depth = maxy - miny
    upper = _clean(scale(base, xfact=upper_ratio, yfact=upper_ratio, origin="centroid"))
    if upper is None:
        return None
    shifted = translate(
        upper,
        xoff=width * distance_ratio if axis == "x" else 0.0,
        yoff=depth * distance_ratio if axis == "y" else 0.0,
    )
    return _clean(shifted.intersection(base))


def _upper_terrace_link(base: Polygon, *, side: str, upper_ratio: float, width_ratio: float, depth_ratio: float) -> Polygon | None:
    upper = _clean(scale(base, xfact=upper_ratio, yfact=upper_ratio, origin="centroid"))
    if upper is None:
        return None
    return _edge_notch(upper, side=side, width_ratio=width_ratio, depth_ratio=depth_ratio)


def _upper_sloped_roof_mass(base: Polygon, *, x_ratio: float, y_ratio: float, upper_ratio: float) -> Polygon | None:
    upper = _clean(scale(base, xfact=upper_ratio, yfact=upper_ratio, origin="centroid"))
    if upper is None:
        return None
    return _clean(scale(upper, xfact=x_ratio, yfact=y_ratio, origin="centroid").intersection(base))


def generate_morphology_variants(base_footprint: Polygon) -> list[MorphologyVariant]:
    """Generate deterministic mass variants from a repaired source footprint."""
    base = _clean(base_footprint)
    if base is None:
        return []

    variants: list[MorphologyVariant] = []

    for factor, label in ((0.92, "inset_light"), (0.82, "inset_strong")):
        fp = _clean(scale(base, xfact=factor, yfact=factor, origin="centroid"))
        if fp is not None:
            variants.append(MorphologyVariant(label, fp, notes=("BCR/FAR 여유를 만드는 inward mass",)))

    for factor, label in ((1.12, "bcr_fill_light"), (1.35, "bcr_fill_mid"), (1.65, "bcr_fill_strong")):
        fp = _clean(scale(base, xfact=factor, yfact=factor, origin="centroid"))
        if fp is not None:
            variants.append(MorphologyVariant(label, fp, notes=("건폐율/용적률 활용도를 높이는 footprint 확장 후보",)))

    for west, north, label in (
        (True, True, "notch_north_west"),
        (False, True, "notch_north_east"),
        (True, False, "notch_south_west"),
        (False, False, "notch_south_east"),
    ):
        fp = _corner_cut(base, west=west, north=north, ratio=0.28)
        if fp is not None:
            variants.append(MorphologyVariant(label, fp, notes=("코너를 비워 채광/개방감 proxy를 올리는 notch",)))

    for side, label in (
        ("north", "court_open_north"),
        ("south", "court_open_south"),
        ("east", "court_open_east"),
        ("west", "court_open_west"),
    ):
        fp = _edge_notch(base, side=side, width_ratio=0.42, depth_ratio=0.34)
        if fp is not None:
            variants.append(MorphologyVariant(label, fp, notes=("한쪽을 깊게 비워 U/L 계열 개방형 매스 생성",)))

    for xfactor, yfactor, xshift, yshift, label in (
        (0.54, 0.96, -0.18, 0.00, "slender_bar_west"),
        (0.54, 0.96, 0.18, 0.00, "slender_bar_east"),
        (0.96, 0.54, 0.00, -0.18, "slender_bar_south"),
        (0.96, 0.54, 0.00, 0.18, "slender_bar_north"),
    ):
        fp = _directional_bar(base, xfactor=xfactor, yfactor=yfactor, xshift=xshift, yshift=yshift)
        if fp is not None:
            variants.append(MorphologyVariant(label, fp, notes=("길쭉한 판상 매스로 방향성과 조망/일조 대안 생성",)))

    for axis, label in (("x", "split_bridge_x"), ("y", "split_bridge_y")):
        fp = _bridged_split(base, axis=axis, gap_ratio=0.24, bridge_ratio=0.20)
        if fp is not None:
            variants.append(MorphologyVariant(label, fp, notes=("Operative Design split을 연결 브릿지형 평면으로 근사",)))

    for angle, label in ((28.0, "branch_y_soft"), (42.0, "branch_y_wide")):
        fp = _branch_plan(base, angle=angle, trunk_ratio=0.30, arm_ratio=0.22)
        if fp is not None:
            variants.append(MorphologyVariant(label, fp, notes=("Operative Design branch 계열의 Y형 매스 대안",)))

    for axis, label in (("x", "pinch_waist_x"), ("y", "pinch_waist_y")):
        fp = _pinch_plan(base, axis=axis, waist_ratio=0.58, depth_ratio=0.42)
        if fp is not None:
            variants.append(MorphologyVariant(label, fp, notes=("Operative Design pinch 계열의 허리 좁힘 매스",)))

    for angle, label in ((28.0, "interlock_cross_soft"), (-34.0, "interlock_cross_diagonal")):
        fp = _interlock_cross(base, angle=angle, bar_ratio=0.34)
        if fp is not None:
            variants.append(MorphologyVariant(label, fp, notes=("Operative Design interlock/overlap 계열의 교차 매스",)))

    for axis, label in (("x", "overlap_slabs_x"), ("y", "overlap_slabs_y")):
        fp = _overlap_shifted_slabs(base, axis=axis, slab_ratio=0.46, shift_ratio=0.18)
        if fp is not None:
            variants.append(MorphologyVariant(label, fp, notes=("Operative Design overlap/slide 계열의 어긋난 slab 매스",)))

    minx, miny, maxx, maxy = base.bounds
    courtyard = box(
        minx + (maxx - minx) * 0.34,
        miny + (maxy - miny) * 0.34,
        minx + (maxx - minx) * 0.66,
        miny + (maxy - miny) * 0.66,
    )
    fp = _clean(base.difference(courtyard))
    if fp is not None and fp.area < base.area * 0.92:
        variants.append(MorphologyVariant("courtyard_void", fp, notes=("중앙 void로 courtyard형 대안 생성",)))

    upper = _clean(scale(base, xfact=0.68, yfact=0.68, origin="centroid"))
    if upper is not None:
        variants.append(MorphologyVariant(
            "terrace_stepback",
            base,
            upper_footprint=upper,
            lower_floor_fraction=0.45,
            notes=("상층 footprint를 축소해 terrace/stepback 대안 생성",),
        ))
        shifted = _clean(translate(upper, xoff=(maxx - minx) * 0.08, yoff=-(maxy - miny) * 0.06).intersection(base))
        if shifted is not None:
            variants.append(MorphologyVariant(
                "shifted_tower",
                base,
                upper_footprint=shifted,
                lower_floor_fraction=0.42,
                notes=("포디움 위 상층부 위치를 이동한 tower 대안",),
            ))

    tapered = _clean(scale(base, xfact=0.72, yfact=0.58, origin="centroid"))
    if tapered is not None:
        variants.append(MorphologyVariant(
            "tapered_slab",
            base,
            upper_footprint=tapered,
            lower_floor_fraction=0.34,
            notes=("Operative Design taper를 층별 footprint 축소로 근사",),
        ))
    graded = _edge_notch(base, side="north", width_ratio=0.58, depth_ratio=0.28)
    if graded is not None:
        variants.append(MorphologyVariant(
            "grade_terrace_north",
            base,
            upper_footprint=graded,
            lower_floor_fraction=0.30,
            notes=("Operative Design grade를 상층 북측 절삭 terrace로 근사",),
        ))
    lifted = _overlap_shifted_slabs(base, axis="x", slab_ratio=0.58, shift_ratio=0.12)
    if lifted is not None:
        upper_lifted = _clean(translate(lifted, xoff=(maxx - minx) * 0.07, yoff=(maxy - miny) * 0.05).intersection(base))
        variants.append(MorphologyVariant(
            "lift_overlap_slabs",
            lifted,
            upper_footprint=upper_lifted,
            lower_floor_fraction=0.38,
            notes=("Operative Design lift+overlap을 포디움/상부 slab 분리로 근사",),
        ))

    for axis, distance, label in (
        ("x", 0.12, "diagonal_connect_step_x"),
        ("y", 0.12, "diagonal_connect_step_y"),
    ):
        upper_diag = _upper_diagonal_connect(base, axis=axis, upper_ratio=0.72, distance_ratio=distance)
        if upper_diag is not None:
            variants.append(MorphologyVariant(
                label,
                base,
                upper_footprint=upper_diag,
                lower_floor_fraction=0.40,
                notes=("계단형 후퇴를 단순 층층 박스가 아니라 사선 연결 가능한 상부 오프셋 매스로 근사",),
                verb_sequence=(
                    {"verb": "base", "params": {"proportion": "site"}},
                    {"verb": "diagonal_connect", "params": {"axis": axis, "upper_ratio": 0.72, "distance_ratio": distance}},
                ),
            ))

    upper_terrace = _upper_terrace_link(base, side="north", upper_ratio=0.84, width_ratio=0.62, depth_ratio=0.22)
    if upper_terrace is not None:
        variants.append(MorphologyVariant(
            "terrace_link_north",
            base,
            upper_footprint=upper_terrace,
            lower_floor_fraction=0.36,
            notes=("북측 일조/테라스 후퇴부를 연결된 terrace-link 단면으로 근사",),
            verb_sequence=(
                {"verb": "base", "params": {"proportion": "site"}},
                {"verb": "terrace_link", "params": {"side": "north", "upper_ratio": 0.84, "width_ratio": 0.62, "depth_ratio": 0.22}},
            ),
        ))

    upper_slope = _upper_sloped_roof_mass(base, x_ratio=0.70, y_ratio=0.92, upper_ratio=0.90)
    if upper_slope is not None:
        variants.append(MorphologyVariant(
            "sloped_roof_mass",
            base,
            upper_footprint=upper_slope,
            lower_floor_fraction=0.50,
            notes=("사선 제한면을 단순 절단선이 아니라 sloped roof mass 디자인 후보로 근사",),
            verb_sequence=(
                {"verb": "base", "params": {"proportion": "site"}},
                {"verb": "sloped_roof_mass", "params": {"upper_ratio": 0.90, "x_ratio": 0.70, "y_ratio": 0.92}},
            ),
        ))

    return variants


__all__ = ["MorphologyVariant", "generate_morphology_variants", "largest_polygon"]
