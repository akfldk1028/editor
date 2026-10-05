"""
Building mass evaluator using Shapely geometry.

Generates building mass from design parameters and calculates
performance metrics (BCR, FAR, daylight score, etc.)

10 mass generation algorithms:

Original (EvoMass-inspired):
  1. Additive (Box-Stacking K=5)        — 29 genes
  2. Subtractive (Void Carving K=3)     — 23 genes
  3. Grid (3x3 Subdivision)             — 22 genes

Typological templates:
  4. L-shape (2-wing perpendicular)     — 11 genes
  5. U-shape (3-wing)                   — 13 genes
  6. Cross (2-bar intersection)         — 10 genes
  7. Courtyard (ring with inner void)   — 12 genes
  8. Tower+Podium (wide base + tower)   — 13 genes
  9. H-shape (2 bars + bridge)          — 13 genes
 10. Radial (6-sector polar cells)      — 16 genes
"""

import logging
import math

from shapely.geometry import Polygon, box
from shapely.affinity import rotate, translate, scale
from shapely.ops import unary_union

from backend.app.modules.design.generation.services.site_geometry import wgs84_to_utm

logger = logging.getLogger(__name__)

# Default floor height (meters)
FLOOR_HEIGHT = 3.0

# Building use types with type-specific floor heights
BUILDING_TYPES = {
    "공동주택": {"label": "공동주택 (아파트)", "floor_height": 2.8},
    "근린생활시설": {"label": "근린생활시설", "floor_height": 3.5},
    "업무시설": {"label": "업무시설 (오피스)", "floor_height": 3.8},
    "판매시설": {"label": "판매시설 (상가)", "floor_height": 4.0},
    "숙박시설": {"label": "숙박시설 (호텔)", "floor_height": 3.0},
    "문화집회시설": {"label": "문화 및 집회시설", "floor_height": 4.5},
    "의료시설": {"label": "의료시설", "floor_height": 3.6},
    "교육연구시설": {"label": "교육연구시설", "floor_height": 3.5},
    "공장": {"label": "공장", "floor_height": 5.0},
    "창고시설": {"label": "창고시설", "floor_height": 6.0},
}


def get_floor_height(building_type: str = "공동주택") -> float:
    """Get floor height for a building type."""
    bt = BUILDING_TYPES.get(building_type)
    return bt["floor_height"] if bt else FLOOR_HEIGHT


# Algorithm-specific gene layouts
# global_base = index where global params start, total = total gene count
ALGO_LAYOUT = {
    "additive":      {"global_base": 25, "total": 29},  # 5 boxes x 5 + 4 global
    "subtractive":   {"global_base": 19, "total": 23},  # 4 block + 3 voids x 5 + 4 global
    "grid":          {"global_base": 18, "total": 22},  # 9 cells x 2 + 4 global
    "lshape":        {"global_base": 7,  "total": 11},  # 7 shape + 4 global
    "ushape":        {"global_base": 9,  "total": 13},  # 9 shape + 4 global
    "cross":         {"global_base": 6,  "total": 10},  # 6 shape + 4 global
    "courtyard":     {"global_base": 8,  "total": 12},  # 8 shape + 4 global
    "tower_podium":  {"global_base": 9,  "total": 13},  # 9 shape + 4 global
    "hshape":        {"global_base": 9,  "total": 13},  # 9 shape + 4 global
    "radial":        {"global_base": 12, "total": 16},  # 12 shape + 4 global
}

# Legacy constants for additive (backward compatibility)
NUM_BOXES = 5
GENES_PER_BOX = 5
_GLOBAL_BASE = NUM_BOXES * GENES_PER_BOX  # 25
IDX_NUM_FLOORS = _GLOBAL_BASE          # gene 25
IDX_ROTATION = _GLOBAL_BASE + 1        # gene 26
IDX_UPPER_SCALE = _GLOBAL_BASE + 2     # gene 27
IDX_STEP_FRAC = _GLOBAL_BASE + 3       # gene 28
TOTAL_GENES = _GLOBAL_BASE + 4         # 29


def _global_idx(algorithm: str, offset: int) -> int:
    """Get global gene index for a given algorithm and offset (0-3)."""
    return ALGO_LAYOUT.get(algorithm, ALGO_LAYOUT["additive"])["global_base"] + offset


def _build_mass_polygon_freeform(inputs: list, site_utm: Polygon) -> tuple[Polygon | None, bool]:
    """
    Create building footprint from K=5 box-stacking (EvoMass).

    Each box is defined by (x_offset, y_offset, width, depth, rotation).
    Boxes are unioned via Shapely unary_union to form the footprint.
    Global rotation (gene 26) is applied to the combined shape.

    Returns:
        (polygon, is_multipolygon): The building polygon and whether the
        union produced disconnected components (MultiPolygon penalty).
    """
    try:
        cx, cy = site_utm.centroid.x, site_utm.centroid.y
        boxes = []
        for i in range(NUM_BOXES):
            base = i * GENES_PER_BOX
            bx = inputs[base][0]
            by = inputs[base + 1][0]
            bw = inputs[base + 2][0]
            bd = inputs[base + 3][0]
            brot = inputs[base + 4][0]

            rect = box(-bw / 2, -bd / 2, bw / 2, bd / 2)
            rect = rotate(rect, brot, origin=(0, 0))
            rect = translate(rect, xoff=cx + bx, yoff=cy + by)
            boxes.append(rect)

        building = unary_union(boxes)

        # Global rotation (gene 26)
        global_rot = inputs[IDX_ROTATION][0]
        building = rotate(building, global_rot, origin=(cx, cy))

        # MultiPolygon → largest polygon only (disconnected mass penalty)
        is_multi = False
        if building.geom_type == 'MultiPolygon':
            is_multi = True
            building = max(building.geoms, key=lambda g: g.area)

        if building.is_empty or building.area < 1.0:
            return None, False

        return building, is_multi

    except (IndexError, TypeError) as e:
        logger.warning(f"Failed to build freeform mass polygon: {e}")
        return None, False


def _build_mass_polygon_subtractive(inputs: list, site_utm: Polygon) -> tuple[Polygon | None, bool]:
    """
    Create building footprint by carving K=3 voids from a site-scaled block.

    Gene layout (19 shape genes):
      Block: [scale_x, scale_y, block_rot, block_inset]   genes 0-3
      Void 0: [vx, vy, vw, vd, vrot]                      genes 4-8
      Void 1: [vx, vy, vw, vd, vrot]                      genes 9-13
      Void 2: [vx, vy, vw, vd, vrot]                      genes 14-18
    """
    try:
        cx, cy = site_utm.centroid.x, site_utm.centroid.y
        minx, miny, maxx, maxy = site_utm.bounds
        bw = (maxx - minx) * inputs[0][0]   # scale_x: 0.4~1.0
        bd = (maxy - miny) * inputs[1][0]   # scale_y: 0.4~1.0
        brot = inputs[2][0]                  # block_rot: 0~180
        inset = inputs[3][0]                 # block_inset: 0~max_dim*0.2

        block = box(cx - bw / 2 + inset, cy - bd / 2 + inset,
                    cx + bw / 2 - inset, cy + bd / 2 - inset)
        block = rotate(block, brot, origin=(cx, cy))

        # Subtract K=3 voids
        for i in range(3):
            base = 4 + i * 5
            vx = inputs[base][0]
            vy = inputs[base + 1][0]
            vw = inputs[base + 2][0]
            vd = inputs[base + 3][0]
            vrot = inputs[base + 4][0]
            void = box(-vw / 2, -vd / 2, vw / 2, vd / 2)
            void = rotate(void, vrot, origin=(0, 0))
            void = translate(void, xoff=cx + vx, yoff=cy + vy)
            block = block.difference(void)

        # Global rotation (gene 20 for subtractive)
        global_base = ALGO_LAYOUT["subtractive"]["global_base"]
        global_rot = inputs[global_base + 1][0]
        block = rotate(block, global_rot, origin=(cx, cy))

        # MultiPolygon handling (void splits the block)
        is_multi = False
        if block.geom_type == 'MultiPolygon':
            is_multi = True
            block = max(block.geoms, key=lambda g: g.area)

        if block.is_empty or block.area < 1.0:
            return None, False
        return block, is_multi

    except (IndexError, TypeError) as e:
        logger.warning(f"Failed to build subtractive mass polygon: {e}")
        return None, False


def _build_mass_polygon_grid(inputs: list, site_utm: Polygon) -> tuple[Polygon | None, bool]:
    """
    Create building footprint from a 3x3 grid subdivision.

    Each cell has on/off threshold + height_ratio.
    Gene layout (18 shape genes):
      Cell (i,j): [threshold, height_ratio]  genes (i*3+j)*2 .. (i*3+j)*2+1
    """
    GRID = 3
    try:
        cx, cy = site_utm.centroid.x, site_utm.centroid.y
        minx, miny, maxx, maxy = site_utm.bounds
        cell_w = (maxx - minx) * 0.9 / GRID
        cell_d = (maxy - miny) * 0.9 / GRID
        origin_x = cx - cell_w * GRID / 2
        origin_y = cy - cell_d * GRID / 2

        cells = []
        for i in range(GRID):
            for j in range(GRID):
                idx = (i * GRID + j) * 2
                threshold = inputs[idx][0]    # 0~1: >0.5 = on
                if threshold > 0.5:
                    cell = box(
                        origin_x + j * cell_w, origin_y + i * cell_d,
                        origin_x + (j + 1) * cell_w, origin_y + (i + 1) * cell_d,
                    )
                    cells.append(cell)

        if not cells:
            return None, False

        building = unary_union(cells)

        # Global rotation
        global_base = ALGO_LAYOUT["grid"]["global_base"]
        global_rot = inputs[global_base + 1][0]  # rotation
        building = rotate(building, global_rot, origin=(cx, cy))

        is_multi = False
        if building.geom_type == 'MultiPolygon':
            is_multi = True
            building = max(building.geoms, key=lambda g: g.area)

        if building.is_empty or building.area < 1.0:
            return None, False
        return building, is_multi

    except (IndexError, TypeError) as e:
        logger.warning(f"Failed to build grid mass polygon: {e}")
        return None, False


def _build_mass_polygon_lshape(inputs: list, site_utm: Polygon) -> tuple[Polygon | None, bool]:
    """
    L-shape: two perpendicular wings. 7 shape genes.
    [wing1_w, wing1_d, wing2_w, wing2_d, junction, side, local_rot]
    + global rotation applied from global gene.
    """
    try:
        cx, cy = site_utm.centroid.x, site_utm.centroid.y
        w1w, w1d = inputs[0][0], inputs[1][0]
        w2w, w2d = inputs[2][0], inputs[3][0]
        junction = inputs[4][0]   # 0~1: where along wing1
        side = inputs[5][0]       # 0~1: >0.5 = top, else bottom
        local_rot = inputs[6][0]  # 0~180

        w1 = box(cx - w1w / 2, cy - w1d / 2, cx + w1w / 2, cy + w1d / 2)
        w2x = cx - w1w / 2 + junction * w1w
        if side > 0.5:
            w2 = box(w2x - w2w / 2, cy + w1d / 2, w2x + w2w / 2, cy + w1d / 2 + w2d)
        else:
            w2 = box(w2x - w2w / 2, cy - w1d / 2 - w2d, w2x + w2w / 2, cy - w1d / 2)

        building = unary_union([w1, w2])
        # Local rotation (shape gene) + global rotation (global gene)
        gb = ALGO_LAYOUT["lshape"]["global_base"]
        global_rot = inputs[gb + 1][0]
        building = rotate(building, local_rot + global_rot, origin=(cx, cy))

        is_multi = False
        if building.geom_type == 'MultiPolygon':
            is_multi = True
            building = max(building.geoms, key=lambda g: g.area)
        if building.is_empty or building.area < 1.0:
            return None, False
        return building, is_multi
    except (IndexError, TypeError) as e:
        logger.warning(f"Failed to build L-shape polygon: {e}")
        return None, False


def _build_mass_polygon_ushape(inputs: list, site_utm: Polygon) -> tuple[Polygon | None, bool]:
    """
    U-shape: base bar + two wings forming U. 9 shape genes.
    [base_w, base_d, left_w, left_d, right_w, right_d, gap, opening_side, local_rot]
    """
    try:
        cx, cy = site_utm.centroid.x, site_utm.centroid.y
        bw, bd = inputs[0][0], inputs[1][0]
        lw, ld = inputs[2][0], inputs[3][0]
        rw, rd = inputs[4][0], inputs[5][0]
        gap = inputs[6][0]          # gap between wings
        opening = inputs[7][0]      # 0~1: controls rotation of U
        local_rot = inputs[8][0]

        # Base bar (bottom of U)
        base = box(cx - bw / 2, cy - bd / 2, cx + bw / 2, cy + bd / 2)

        # Left wing (up from left end of base, inset by gap/2)
        lx = cx - bw / 2
        left = box(lx, cy + bd / 2, lx + lw, cy + bd / 2 + ld)

        # Right wing (up from right end of base, separated by gap)
        rx = cx + bw / 2 - rw
        right = box(rx, cy + bd / 2, rx + rw, cy + bd / 2 + rd)

        building = unary_union([base, left, right])
        # Local rotation + global rotation
        gb = ALGO_LAYOUT["ushape"]["global_base"]
        global_rot = inputs[gb + 1][0]
        total_rot = opening * 360 + local_rot + global_rot
        building = rotate(building, total_rot, origin=(cx, cy))

        is_multi = False
        if building.geom_type == 'MultiPolygon':
            is_multi = True
            building = max(building.geoms, key=lambda g: g.area)
        if building.is_empty or building.area < 1.0:
            return None, False
        return building, is_multi
    except (IndexError, TypeError) as e:
        logger.warning(f"Failed to build U-shape polygon: {e}")
        return None, False


def _build_mass_polygon_cross(inputs: list, site_utm: Polygon) -> tuple[Polygon | None, bool]:
    """
    Cross/Plus shape: two intersecting perpendicular bars. 6 shape genes.
    [bar1_w, bar1_d, bar2_w, bar2_d, offset_x, offset_y]
    """
    try:
        cx, cy = site_utm.centroid.x, site_utm.centroid.y
        b1w, b1d = inputs[0][0], inputs[1][0]
        b2w, b2d = inputs[2][0], inputs[3][0]
        ox, oy = inputs[4][0], inputs[5][0]

        # Horizontal bar
        bar1 = box(cx - b1w / 2 + ox, cy - b1d / 2 + oy,
                   cx + b1w / 2 + ox, cy + b1d / 2 + oy)
        # Vertical bar (perpendicular)
        bar2 = box(cx - b2w / 2 + ox, cy - b2d / 2 + oy,
                   cx + b2w / 2 + ox, cy + b2d / 2 + oy)
        bar2 = rotate(bar2, 90, origin=(cx + ox, cy + oy))

        building = unary_union([bar1, bar2])

        # Apply global rotation
        gb = ALGO_LAYOUT["cross"]["global_base"]
        global_rot = inputs[gb + 1][0]
        building = rotate(building, global_rot, origin=(cx, cy))

        is_multi = False
        if building.geom_type == 'MultiPolygon':
            is_multi = True
            building = max(building.geoms, key=lambda g: g.area)
        if building.is_empty or building.area < 1.0:
            return None, False
        return building, is_multi
    except (IndexError, TypeError) as e:
        logger.warning(f"Failed to build cross polygon: {e}")
        return None, False


def _build_mass_polygon_courtyard(inputs: list, site_utm: Polygon) -> tuple[Polygon | None, bool]:
    """
    Courtyard: outer rectangle with inner void. 8 shape genes.
    [outer_w, outer_d, wall_t, court_x, court_y, court_w, court_d, opening_w]
    """
    try:
        cx, cy = site_utm.centroid.x, site_utm.centroid.y
        ow, od = inputs[0][0], inputs[1][0]
        wall_t = inputs[2][0]       # minimum wall thickness
        crtx, crty = inputs[3][0], inputs[4][0]  # courtyard offset
        crtw, crtd = inputs[5][0], inputs[6][0]  # courtyard size
        opening = inputs[7][0]      # 0~1: opening width on south side

        outer = box(cx - ow / 2, cy - od / 2, cx + ow / 2, cy + od / 2)

        # Inner courtyard (clamp to ensure minimum wall thickness)
        max_crt_w = max(1.0, ow - 2 * wall_t)
        max_crt_d = max(1.0, od - 2 * wall_t)
        crtw = min(crtw, max_crt_w)
        crtd = min(crtd, max_crt_d)

        court = box(cx + crtx - crtw / 2, cy + crty - crtd / 2,
                    cx + crtx + crtw / 2, cy + crty + crtd / 2)
        building = outer.difference(court)

        # Optional opening (cut through south wall)
        if opening > 0.3:
            open_w = opening * crtw
            cut = box(cx + crtx - open_w / 2, cy - od / 2 - 1,
                      cx + crtx + open_w / 2, cy + crty - crtd / 2)
            building = building.difference(cut)

        # Apply global rotation
        gb = ALGO_LAYOUT["courtyard"]["global_base"]
        global_rot = inputs[gb + 1][0]
        building = rotate(building, global_rot, origin=(cx, cy))

        is_multi = False
        if building.geom_type == 'MultiPolygon':
            is_multi = True
            building = max(building.geoms, key=lambda g: g.area)
        if building.is_empty or building.area < 1.0:
            return None, False
        return building, is_multi
    except (IndexError, TypeError) as e:
        logger.warning(f"Failed to build courtyard polygon: {e}")
        return None, False


def _build_mass_polygon_tower_podium(inputs: list, site_utm: Polygon) -> tuple[Polygon | None, bool]:
    """
    Tower + Podium: wide podium base with narrower tower.
    Returns union(podium, tower) so both are visible on map.
    The step-back genes (upper_scale, step_fraction) naturally create
    the two-tier height effect in _compute_metrics.

    9 shape genes:
    [podium_w, podium_d, podium_h_ratio, tower_x, tower_y, tower_w, tower_d, tower_rot, setback]
    """
    try:
        cx, cy = site_utm.centroid.x, site_utm.centroid.y
        pw, pd = inputs[0][0], inputs[1][0]
        tx, ty = inputs[3][0], inputs[4][0]
        tw, td = inputs[5][0], inputs[6][0]
        trot = inputs[7][0]
        setback = inputs[8][0]

        podium = box(cx - pw / 2, cy - pd / 2, cx + pw / 2, cy + pd / 2)

        tw = min(tw, pw - 2 * setback)
        td = min(td, pd - 2 * setback)
        if tw < 3.0 or td < 3.0:
            return podium, False

        tower = box(-tw / 2, -td / 2, tw / 2, td / 2)
        tower = rotate(tower, trot, origin=(0, 0))
        tower = translate(tower, xoff=cx + tx, yoff=cy + ty)

        # Union so footprint includes both podium and tower
        building = unary_union([podium, tower])

        # Apply global rotation
        gb = ALGO_LAYOUT["tower_podium"]["global_base"]
        global_rot = inputs[gb + 1][0]
        building = rotate(building, global_rot, origin=(cx, cy))

        is_multi = False
        if building.geom_type == 'MultiPolygon':
            is_multi = True
            building = max(building.geoms, key=lambda g: g.area)
        if building.is_empty or building.area < 1.0:
            return None, False
        return building, is_multi
    except (IndexError, TypeError) as e:
        logger.warning(f"Failed to build tower+podium polygon: {e}")
        return None, False


def _build_mass_polygon_hshape(inputs: list, site_utm: Polygon) -> tuple[Polygon | None, bool]:
    """
    H-shape: two parallel bars connected by a bridge. 9 shape genes.
    [bar1_w, bar1_d, bar2_w, bar2_d, gap, bridge_w, bridge_d, bridge_offset, local_rot]
    """
    try:
        cx, cy = site_utm.centroid.x, site_utm.centroid.y
        b1w, b1d = inputs[0][0], inputs[1][0]
        b2w, b2d = inputs[2][0], inputs[3][0]
        gap = inputs[4][0]
        brw, brd = inputs[5][0], inputs[6][0]
        br_offset = inputs[7][0]   # 0~1: bridge vertical position
        local_rot = inputs[8][0]

        half_gap = gap / 2

        # Left bar
        bar1 = box(cx - half_gap - b1w, cy - b1d / 2,
                   cx - half_gap, cy + b1d / 2)
        # Right bar
        bar2 = box(cx + half_gap, cy - b2d / 2,
                   cx + half_gap + b2w, cy + b2d / 2)

        # Bridge connecting them
        min_d = min(b1d, b2d)
        br_y = cy - min_d / 2 + br_offset * (min_d - brd)
        bridge = box(cx - half_gap, br_y, cx + half_gap, br_y + brd)

        building = unary_union([bar1, bar2, bridge])
        # Local rotation + global rotation
        gb = ALGO_LAYOUT["hshape"]["global_base"]
        global_rot = inputs[gb + 1][0]
        building = rotate(building, local_rot + global_rot, origin=(cx, cy))

        is_multi = False
        if building.geom_type == 'MultiPolygon':
            is_multi = True
            building = max(building.geoms, key=lambda g: g.area)
        if building.is_empty or building.area < 1.0:
            return None, False
        return building, is_multi
    except (IndexError, TypeError) as e:
        logger.warning(f"Failed to build H-shape polygon: {e}")
        return None, False


def _build_mass_polygon_radial(inputs: list, site_utm: Polygon) -> tuple[Polygon | None, bool]:
    """
    Radial: 6 pie-shaped sectors in polar coordinates. 12 shape genes.
    Each sector: [on_threshold, radius_ratio]
    Sectors are 60° each, creating fan/circular building forms.
    """
    NUM_SECTORS = 6
    ANGLE_PER = 360.0 / NUM_SECTORS
    try:
        cx, cy = site_utm.centroid.x, site_utm.centroid.y
        minx, miny, maxx, maxy = site_utm.bounds
        max_r = min(maxx - cx, maxy - cy) * 0.8

        sectors = []
        for i in range(NUM_SECTORS):
            idx = i * 2
            threshold = inputs[idx][0]
            radius = inputs[idx + 1][0] * max_r

            if threshold > 0.4 and radius > 2.0:
                # Create pie-shaped sector
                start_angle = i * ANGLE_PER
                points = [(cx, cy)]  # center point
                # Arc points (8 subdivisions per sector for smoothness)
                for k in range(9):
                    angle_rad = math.radians(start_angle + k * ANGLE_PER / 8)
                    px = cx + radius * math.cos(angle_rad)
                    py = cy + radius * math.sin(angle_rad)
                    points.append((px, py))
                points.append((cx, cy))  # close
                if len(points) >= 4:
                    sector = Polygon(points)
                    if sector.is_valid and sector.area > 1.0:
                        sectors.append(sector)

        if not sectors:
            return None, False

        building = unary_union(sectors)

        # Apply global rotation
        gb = ALGO_LAYOUT["radial"]["global_base"]
        global_rot = inputs[gb + 1][0]
        building = rotate(building, global_rot, origin=(cx, cy))

        is_multi = False
        if building.geom_type == 'MultiPolygon':
            is_multi = True
            building = max(building.geoms, key=lambda g: g.area)
        if building.is_empty or building.area < 1.0:
            return None, False
        return building, is_multi
    except (IndexError, TypeError) as e:
        logger.warning(f"Failed to build radial polygon: {e}")
        return None, False


# Algorithm dispatch table
BUILDERS = {
    "additive": _build_mass_polygon_freeform,
    "subtractive": _build_mass_polygon_subtractive,
    "grid": _build_mass_polygon_grid,
    "lshape": _build_mass_polygon_lshape,
    "ushape": _build_mass_polygon_ushape,
    "cross": _build_mass_polygon_cross,
    "courtyard": _build_mass_polygon_courtyard,
    "tower_podium": _build_mass_polygon_tower_podium,
    "hshape": _build_mass_polygon_hshape,
    "radial": _build_mass_polygon_radial,
}


def evaluate_designs(designs, site_polygon: Polygon, site_area_m2: float,
                     outputs_def: list[dict] | None = None,
                     building_type: str = "공동주택",
                     algorithm: str = "additive",
                     enable_repair: bool = False,
                     repair_limits=None,
                     sunlight_envelope: dict | None = None) -> list[list[float]]:
    """
    Evaluate a batch of Design objects for building mass performance.

    Args:
        designs: list of Design objects with .get_inputs()
        site_polygon: Site boundary in WGS84 (Shapely Polygon)
        site_area_m2: Site area in square meters (pre-computed)
        outputs_def: job_spec["outputs"] — determines which metrics to return and in what order
        building_type: Korean building use type key (e.g. "공동주택", "업무시설")
        enable_repair: Phase 1 A6 — repair operator로 hard constraint 강제 (default False)
        repair_limits: RegulationLimits 인스턴스 (None이면 outputs_def에서 자동 추출)

    Returns:
        list of output value lists, one per design.
        Order matches outputs_def exactly.
    """
    site_utm = wgs84_to_utm(site_polygon)
    results = []

    # A6 — repair limits 자동 추출 (outputs_def에서 constraint 값 가져옴)
    if enable_repair and repair_limits is None:
        repair_limits = _build_repair_limits_from_outputs(outputs_def, building_type)

    for des in designs:
        inputs = des.get_inputs()
        metrics = _compute_metrics(
            inputs, site_utm, site_area_m2, building_type, algorithm,
            enable_repair=enable_repair,
            repair_limits=repair_limits,
            sunlight_envelope=sunlight_envelope,
        )
        result = _pick_outputs(metrics, outputs_def)
        results.append(result)

    return results


def _build_repair_limits_from_outputs(outputs_def, building_type: str):
    """A6 — outputs_def constraint 값으로 RegulationLimits 자동 구성."""
    from backend.app.modules.design.generation.services.repair_operator import RegulationLimits

    limits = RegulationLimits()
    limits.floor_height_m = get_floor_height(building_type)
    if not outputs_def:
        return limits
    for c in outputs_def:
        if c.get("type") != "Constraint":
            continue
        name = c.get("name")
        val = float(c.get("val", 0))
        if name == "bcr":
            limits.bcr_limit_pct = val
        elif name == "far":
            limits.far_limit_pct = val
        elif name == "height":
            limits.height_limit_m = val
        elif name == "setback":
            limits.adjacent_setback_m = val
        elif name == "building_line_setback":  # exp003 발견 — 도로 후퇴
            limits.road_setback_m = val
    return limits


# Maps output names to metric keys
_METRIC_MAP = {
    "floor_area": "floor_area",
    "daylight_score": "daylight_score",
    "bcr": "bcr",
    "far": "far",
    "height": "height",
    "setback": "min_setback",
    "building_line_setback": "min_setback",
    "landscaping_pct": "open_pct",
    "compactness": "compactness",         # exp006 4-obj
    "stepback_factor": "stepback_factor", # exp006 4-obj
}


def _pick_outputs(metrics: dict, outputs_def: list[dict] | None) -> list[float]:
    """Pick metric values in the order defined by outputs_def."""
    if not outputs_def:
        # Fallback: return all in default order
        return [
            metrics["floor_area"],
            metrics["daylight_score"],
            metrics["bcr"],
            metrics["far"],
            metrics["height"],
            metrics["min_setback"],
            metrics["open_pct"],
        ]

    result = []
    for out in outputs_def:
        name = out["name"]
        key = _METRIC_MAP.get(name, name)
        result.append(metrics.get(key, 0.0))
    return result


def _compute_metrics(inputs: list, site_utm: Polygon, site_area_m2: float,
                     building_type: str = "공동주택",
                     algorithm: str = "additive",
                     enable_repair: bool = False,
                     repair_limits=None,
                     sunlight_envelope: dict | None = None) -> dict:
    """
    Compute all available metrics for a single design. Returns dict.

    A6 — enable_repair=True 시 repair_operator로 footprint/floors 자동 수정.
    Penalty가 0이 되도록 hard constraint 강제.
    """
    builder = BUILDERS.get(algorithm, _build_mass_polygon_freeform)
    building, is_multi = builder(inputs, site_utm)

    # Default infeasible values
    defaults = {
        "floor_area": 0.0,
        "daylight_score": 0.0,
        "bcr": 100.0,
        "far": 100.0,
        "height": 0.0,
        "min_setback": 0.0,
        "open_pct": 0.0,
    }

    if building is None or building.is_empty:
        return defaults

    # Global gene indices depend on algorithm
    gb = _global_idx(algorithm, 0)  # global_base
    num_floors = max(1, round(inputs[gb][0]))
    floor_height = get_floor_height(building_type)
    height = num_floors * floor_height

    # Clip building to site boundary
    footprint = building.intersection(site_utm)
    if footprint.is_empty:
        return defaults

    # A6 — Repair operator: envelope/BCR/FAR/height hard constraint 강제
    if enable_repair and repair_limits is not None:
        from backend.app.modules.design.generation.services.repair_operator import repair_design
        from shapely.geometry import MultiPolygon
        repaired_fp, repaired_floors, _actions = repair_design(
            footprint, site_utm, num_floors, repair_limits,
            sunlight_envelope=sunlight_envelope,
        )
        if repaired_fp is None:
            return defaults
        footprint = repaired_fp
        num_floors = repaired_floors
        height = num_floors * floor_height
        # Repair는 MultiPolygon → largest 단일 polygon으로 변환. is_multi 재계산.
        is_multi = isinstance(footprint, MultiPolygon)

    footprint_area = footprint.area

    # Step-back: upper floors use scaled-down footprint
    idx_upper = gb + 2
    idx_step = gb + 3
    upper_scale = max(0.5, min(1.0, inputs[idx_upper][0])) if len(inputs) > idx_upper else 1.0
    step_frac = max(0.3, min(0.8, inputs[idx_step][0])) if len(inputs) > idx_step else 1.0

    has_stepback = upper_scale < 0.98 and step_frac < 0.95
    # Code review fix (2026-05-06): repair가 num_floors=1로 줄였으면 step-back 의미 없음.
    # B7 explanation_generator가 stepback_factor 0이 아닌 값을 보고 "상층 후퇴" 잘못 설명할 수 있음.
    if num_floors < 2:
        has_stepback = False
    if has_stepback:
        step_floor = max(1, round(num_floors * step_frac))
        lower_floors = step_floor
        upper_floors = num_floors - step_floor
        # Upper footprint: scale from centroid
        upper_fp = scale(footprint, xfact=upper_scale, yfact=upper_scale, origin='centroid')
        upper_fp = upper_fp.intersection(site_utm)
        upper_area = upper_fp.area if not upper_fp.is_empty else 0
        floor_area = footprint_area * lower_floors + upper_area * upper_floors
    else:
        floor_area = footprint_area * num_floors

    # BCR = building footprint / site area x 100 (based on largest footprint)
    bcr = (footprint_area / site_area_m2) * 100 if site_area_m2 > 0 else 100

    # FAR = total floor area / site area x 100
    far = (floor_area / site_area_m2) * 100 if site_area_m2 > 0 else 100

    # Disconnected mass penalty: force constraint violation
    if is_multi:
        bcr = 200.0
        far = 9999.0

    # Daylight score: open area + perimeter + step-back bonus
    open_ratio = 1.0 - (footprint_area / site_area_m2) if site_area_m2 > 0 else 0
    if footprint_area > 0:
        perimeter_ratio = footprint.length / math.sqrt(footprint_area)
    else:
        perimeter_ratio = 0
    stepback_bonus = (1 - upper_scale) * 0.3 if has_stepback else 0
    daylight_score = open_ratio * 0.5 + min(perimeter_ratio / 8.0, 1.0) * 0.3 + stepback_bonus + 0.2
    daylight_score = round(min(daylight_score * 100, 100), 2)

    # Minimum setback from site boundary
    if site_utm.contains(footprint):
        min_setback = footprint.distance(site_utm.boundary)
    else:
        min_setback = 0.0

    # Open area % (landscaping proxy)
    open_pct = round(open_ratio * 100, 2)

    # exp006 (2026-05-06): 4 objective 비교용 추가 metric
    # compactness — perimeter² / area (lower=compact). 정사각형≈16, 길쭉/요철 매스↑
    if footprint_area > 0:
        compactness = round((footprint.length ** 2) / footprint_area, 2)
    else:
        compactness = 9999.0
    # stepback_factor — upper floor scale (1=균일적층, 0.5=절반축소). lower=상층 더 양보
    stepback_factor = round(1.0 - upper_scale, 4) if has_stepback else 0.0

    return {
        "floor_area": round(floor_area, 2),
        "daylight_score": daylight_score,
        "bcr": round(bcr, 2),
        "far": round(far, 2),
        "height": round(height, 2),
        "min_setback": round(min_setback, 2),
        "open_pct": open_pct,
        "compactness": compactness,
        "stepback_factor": stepback_factor,
    }
