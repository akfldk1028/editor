"""
Bridge between land/ regulation results and GA constraints.

Converts regulation_calculator output into GA constraint definitions
that the optimization engine understands.

Three algorithm gene layouts:
  additive (29), subtractive (23), grid (22) — all Continuous.
"""

import logging
import math

logger = logging.getLogger(__name__)


def regulations_to_constraints(regulation_result: dict) -> list[dict]:
    """
    Convert land/analyze regulation result to GA constraint list.

    Args:
        regulation_result: Output from land.services.regulation_calculator.calculate_all()
                          or from POST /land/analyze/ response

    Returns:
        List of constraint dicts for GA job spec outputs.
    """
    constraints = []
    coverage = regulation_result.get("municipal_coverage")
    if coverage is not None:
        if not isinstance(coverage, dict) or coverage.get("status") != "available_snapshot":
            raise ValueError("binding municipal ordinance caps need evidence before geometry generation")
        for key in ("bcr_pct", "far_pct"):
            value = regulation_result.get(key)
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or value <= 0):
                raise ValueError("binding BCR/FAR caps must both be finite positive values")

    # BCR (Building Coverage Ratio) — must be less than limit
    bcr = regulation_result.get("bcr_pct")
    if "bcr_pct" not in regulation_result:
        bcr = regulation_result.get("bcr_limit")
    if bcr is not None:
        constraints.append({
            "name": "bcr",
            "type": "Constraint",
            "Requirement": "Less than",
            "val": float(bcr),
            "unit": "%",
            "label": f"건폐율 ≤ {bcr}%",
        })

    # FAR (Floor Area Ratio) — must be less than limit
    far = regulation_result.get("far_pct")
    if "far_pct" not in regulation_result:
        far = regulation_result.get("far_limit")
    if far is not None:
        constraints.append({
            "name": "far",
            "type": "Constraint",
            "Requirement": "Less than",
            "val": float(far),
            "unit": "%",
            "label": f"용적률 ≤ {far}%",
        })

    # Height limit
    height = regulation_result.get("height_limit_m")
    if height is not None:
        constraints.append({
            "name": "height",
            "type": "Constraint",
            "Requirement": "Less than",
            "val": float(height),
            "unit": "m",
            "label": f"높이 ≤ {height}m",
        })

    # Adjacent setback
    setback = regulation_result.get("adjacent_setback_m")
    if setback is not None:
        constraints.append({
            "name": "setback",
            "type": "Constraint",
            "Requirement": "Greater than",
            "val": float(setback),
            "unit": "m",
            "label": f"인접대지 이격 ≥ {setback}m",
        })

    # Building line setback
    bline = regulation_result.get("building_line_setback_m")
    if bline is not None:
        constraints.append({
            "name": "building_line_setback",
            "type": "Constraint",
            "Requirement": "Greater than",
            "val": float(bline),
            "unit": "m",
            "label": f"건축선 후퇴 ≥ {bline}m",
        })

    # Landscaping minimum %
    landscape = regulation_result.get("landscaping_min_pct")
    if landscape is not None:
        constraints.append({
            "name": "landscaping_pct",
            "type": "Constraint",
            "Requirement": "Greater than",
            "val": float(landscape),
            "unit": "%",
            "label": f"조경면적 ≥ {landscape}%",
        })

    return constraints


# Type-specific Pareto objectives
# Residential/educational: maximize floor area + daylight
# Commercial/industrial: maximize floor area + open space (parking/access)
_TYPE_OBJECTIVES = {
    "공동주택":     [{"name": "floor_area", "type": "Objective", "Goal": "Maximize"},
                    {"name": "daylight_score", "type": "Objective", "Goal": "Maximize"}],
    "근린생활시설": [{"name": "floor_area", "type": "Objective", "Goal": "Maximize"},
                    {"name": "landscaping_pct", "type": "Objective", "Goal": "Maximize"}],
    "업무시설":     [{"name": "floor_area", "type": "Objective", "Goal": "Maximize"},
                    {"name": "landscaping_pct", "type": "Objective", "Goal": "Maximize"}],
    "판매시설":     [{"name": "floor_area", "type": "Objective", "Goal": "Maximize"},
                    {"name": "landscaping_pct", "type": "Objective", "Goal": "Maximize"}],
    "숙박시설":     [{"name": "floor_area", "type": "Objective", "Goal": "Maximize"},
                    {"name": "daylight_score", "type": "Objective", "Goal": "Maximize"}],
    "문화집회시설": [{"name": "floor_area", "type": "Objective", "Goal": "Maximize"},
                    {"name": "setback", "type": "Objective", "Goal": "Maximize"}],
    "의료시설":     [{"name": "floor_area", "type": "Objective", "Goal": "Maximize"},
                    {"name": "daylight_score", "type": "Objective", "Goal": "Maximize"}],
    "교육연구시설": [{"name": "floor_area", "type": "Objective", "Goal": "Maximize"},
                    {"name": "daylight_score", "type": "Objective", "Goal": "Maximize"}],
    "공장":         [{"name": "floor_area", "type": "Objective", "Goal": "Maximize"},
                    {"name": "landscaping_pct", "type": "Objective", "Goal": "Maximize"}],
    "창고시설":     [{"name": "floor_area", "type": "Objective", "Goal": "Maximize"},
                    {"name": "landscaping_pct", "type": "Objective", "Goal": "Maximize"}],
}

_DEFAULT_OBJECTIVES = [
    {"name": "floor_area", "type": "Objective", "Goal": "Maximize"},
    {"name": "daylight_score", "type": "Objective", "Goal": "Maximize"},
]


def _global_inputs(max_floors: int) -> list[dict]:
    """4 global params shared by all algorithms."""
    return [
        {"name": "num_floors", "type": "Continuous",
         "Min": 1, "Max": max_floors, "Set length": 1},
        {"name": "rotation", "type": "Continuous",
         "Min": 0, "Max": 180, "Set length": 1},
        {"name": "upper_scale", "type": "Continuous",
         "Min": 0.5, "Max": 1.0, "Set length": 1},
        {"name": "step_fraction", "type": "Continuous",
         "Min": 0.3, "Max": 0.8, "Set length": 1},
    ]


def _build_additive_inputs(max_dim: float, min_dim: float, max_floors: int) -> list[dict]:
    """29 genes: 5 boxes x 5 + 4 global."""
    inputs = []
    for i in range(5):
        inputs.extend([
            {"name": f"b{i}_x", "type": "Continuous",
             "Min": -max_dim * 0.5, "Max": max_dim * 0.5, "Set length": 1},
            {"name": f"b{i}_y", "type": "Continuous",
             "Min": -max_dim * 0.5, "Max": max_dim * 0.5, "Set length": 1},
            {"name": f"b{i}_w", "type": "Continuous",
             "Min": min_dim, "Max": max_dim * 0.6, "Set length": 1},
            {"name": f"b{i}_d", "type": "Continuous",
             "Min": min_dim, "Max": max_dim * 0.6, "Set length": 1},
            {"name": f"b{i}_rot", "type": "Continuous",
             "Min": 0, "Max": 180, "Set length": 1},
        ])
    inputs.extend(_global_inputs(max_floors))
    return inputs


def _build_subtractive_inputs(max_dim: float, min_dim: float, max_floors: int) -> list[dict]:
    """23 genes: 4 block + 3 voids x 5 + 4 global."""
    inputs = [
        {"name": "scale_x", "type": "Continuous",
         "Min": 0.4, "Max": 1.0, "Set length": 1},
        {"name": "scale_y", "type": "Continuous",
         "Min": 0.4, "Max": 1.0, "Set length": 1},
        {"name": "block_rot", "type": "Continuous",
         "Min": 0, "Max": 180, "Set length": 1},
        {"name": "block_inset", "type": "Continuous",
         "Min": 0, "Max": max_dim * 0.2, "Set length": 1},
    ]
    for i in range(3):
        inputs.extend([
            {"name": f"v{i}_x", "type": "Continuous",
             "Min": -max_dim * 0.4, "Max": max_dim * 0.4, "Set length": 1},
            {"name": f"v{i}_y", "type": "Continuous",
             "Min": -max_dim * 0.4, "Max": max_dim * 0.4, "Set length": 1},
            {"name": f"v{i}_w", "type": "Continuous",
             "Min": min_dim, "Max": max_dim * 0.5, "Set length": 1},
            {"name": f"v{i}_d", "type": "Continuous",
             "Min": min_dim, "Max": max_dim * 0.5, "Set length": 1},
            {"name": f"v{i}_rot", "type": "Continuous",
             "Min": 0, "Max": 180, "Set length": 1},
        ])
    inputs.extend(_global_inputs(max_floors))
    return inputs


def _build_grid_inputs(max_dim: float, min_dim: float, max_floors: int) -> list[dict]:
    """22 genes: 9 cells x 2 + 4 global."""
    inputs = []
    for i in range(3):
        for j in range(3):
            inputs.extend([
                {"name": f"cell_{i}_{j}_on", "type": "Continuous",
                 "Min": 0, "Max": 1, "Set length": 1},
                {"name": f"cell_{i}_{j}_h", "type": "Continuous",
                 "Min": 0.3, "Max": 1.0, "Set length": 1},
            ])
    inputs.extend(_global_inputs(max_floors))
    return inputs


def _build_lshape_inputs(max_dim: float, min_dim: float, max_floors: int) -> list[dict]:
    """11 genes: 7 shape + 4 global."""
    return [
        {"name": "wing1_w", "type": "Continuous", "Min": min_dim, "Max": max_dim * 0.7, "Set length": 1},
        {"name": "wing1_d", "type": "Continuous", "Min": min_dim, "Max": max_dim * 0.4, "Set length": 1},
        {"name": "wing2_w", "type": "Continuous", "Min": min_dim, "Max": max_dim * 0.4, "Set length": 1},
        {"name": "wing2_d", "type": "Continuous", "Min": min_dim, "Max": max_dim * 0.7, "Set length": 1},
        {"name": "junction", "type": "Continuous", "Min": 0, "Max": 1, "Set length": 1},
        {"name": "side", "type": "Continuous", "Min": 0, "Max": 1, "Set length": 1},
        {"name": "local_rot", "type": "Continuous", "Min": 0, "Max": 180, "Set length": 1},
    ] + _global_inputs(max_floors)


def _build_ushape_inputs(max_dim: float, min_dim: float, max_floors: int) -> list[dict]:
    """13 genes: 9 shape + 4 global."""
    return [
        {"name": "base_w", "type": "Continuous", "Min": min_dim * 2, "Max": max_dim * 0.8, "Set length": 1},
        {"name": "base_d", "type": "Continuous", "Min": min_dim, "Max": max_dim * 0.3, "Set length": 1},
        {"name": "left_w", "type": "Continuous", "Min": min_dim, "Max": max_dim * 0.3, "Set length": 1},
        {"name": "left_d", "type": "Continuous", "Min": min_dim, "Max": max_dim * 0.6, "Set length": 1},
        {"name": "right_w", "type": "Continuous", "Min": min_dim, "Max": max_dim * 0.3, "Set length": 1},
        {"name": "right_d", "type": "Continuous", "Min": min_dim, "Max": max_dim * 0.6, "Set length": 1},
        {"name": "gap", "type": "Continuous", "Min": min_dim, "Max": max_dim * 0.5, "Set length": 1},
        {"name": "opening_side", "type": "Continuous", "Min": 0, "Max": 1, "Set length": 1},
        {"name": "local_rot", "type": "Continuous", "Min": 0, "Max": 180, "Set length": 1},
    ] + _global_inputs(max_floors)


def _build_cross_inputs(max_dim: float, min_dim: float, max_floors: int) -> list[dict]:
    """10 genes: 6 shape + 4 global."""
    return [
        {"name": "bar1_w", "type": "Continuous", "Min": min_dim * 2, "Max": max_dim * 0.8, "Set length": 1},
        {"name": "bar1_d", "type": "Continuous", "Min": min_dim, "Max": max_dim * 0.35, "Set length": 1},
        {"name": "bar2_w", "type": "Continuous", "Min": min_dim * 2, "Max": max_dim * 0.8, "Set length": 1},
        {"name": "bar2_d", "type": "Continuous", "Min": min_dim, "Max": max_dim * 0.35, "Set length": 1},
        {"name": "offset_x", "type": "Continuous", "Min": -max_dim * 0.2, "Max": max_dim * 0.2, "Set length": 1},
        {"name": "offset_y", "type": "Continuous", "Min": -max_dim * 0.2, "Max": max_dim * 0.2, "Set length": 1},
    ] + _global_inputs(max_floors)


def _build_courtyard_inputs(max_dim: float, min_dim: float, max_floors: int) -> list[dict]:
    """12 genes: 8 shape + 4 global."""
    return [
        {"name": "outer_w", "type": "Continuous", "Min": min_dim * 3, "Max": max_dim * 0.9, "Set length": 1},
        {"name": "outer_d", "type": "Continuous", "Min": min_dim * 3, "Max": max_dim * 0.9, "Set length": 1},
        {"name": "wall_t", "type": "Continuous", "Min": min_dim, "Max": max_dim * 0.25, "Set length": 1},
        {"name": "court_x", "type": "Continuous", "Min": -max_dim * 0.1, "Max": max_dim * 0.1, "Set length": 1},
        {"name": "court_y", "type": "Continuous", "Min": -max_dim * 0.1, "Max": max_dim * 0.1, "Set length": 1},
        {"name": "court_w", "type": "Continuous", "Min": min_dim, "Max": max_dim * 0.5, "Set length": 1},
        {"name": "court_d", "type": "Continuous", "Min": min_dim, "Max": max_dim * 0.5, "Set length": 1},
        {"name": "opening", "type": "Continuous", "Min": 0, "Max": 1, "Set length": 1},
    ] + _global_inputs(max_floors)


def _build_tower_podium_inputs(max_dim: float, min_dim: float, max_floors: int) -> list[dict]:
    """13 genes: 9 shape + 4 global."""
    return [
        {"name": "podium_w", "type": "Continuous", "Min": min_dim * 3, "Max": max_dim * 0.9, "Set length": 1},
        {"name": "podium_d", "type": "Continuous", "Min": min_dim * 3, "Max": max_dim * 0.9, "Set length": 1},
        {"name": "podium_h_ratio", "type": "Continuous", "Min": 0.1, "Max": 0.5, "Set length": 1},
        {"name": "tower_x", "type": "Continuous", "Min": -max_dim * 0.2, "Max": max_dim * 0.2, "Set length": 1},
        {"name": "tower_y", "type": "Continuous", "Min": -max_dim * 0.2, "Max": max_dim * 0.2, "Set length": 1},
        {"name": "tower_w", "type": "Continuous", "Min": min_dim * 2, "Max": max_dim * 0.5, "Set length": 1},
        {"name": "tower_d", "type": "Continuous", "Min": min_dim * 2, "Max": max_dim * 0.5, "Set length": 1},
        {"name": "tower_rot", "type": "Continuous", "Min": 0, "Max": 90, "Set length": 1},
        {"name": "setback", "type": "Continuous", "Min": 0, "Max": max_dim * 0.15, "Set length": 1},
    ] + _global_inputs(max_floors)


def _build_hshape_inputs(max_dim: float, min_dim: float, max_floors: int) -> list[dict]:
    """13 genes: 9 shape + 4 global."""
    return [
        {"name": "bar1_w", "type": "Continuous", "Min": min_dim, "Max": max_dim * 0.35, "Set length": 1},
        {"name": "bar1_d", "type": "Continuous", "Min": min_dim * 2, "Max": max_dim * 0.8, "Set length": 1},
        {"name": "bar2_w", "type": "Continuous", "Min": min_dim, "Max": max_dim * 0.35, "Set length": 1},
        {"name": "bar2_d", "type": "Continuous", "Min": min_dim * 2, "Max": max_dim * 0.8, "Set length": 1},
        {"name": "gap", "type": "Continuous", "Min": min_dim, "Max": max_dim * 0.4, "Set length": 1},
        {"name": "bridge_w", "type": "Continuous", "Min": min_dim, "Max": max_dim * 0.4, "Set length": 1},
        {"name": "bridge_d", "type": "Continuous", "Min": min_dim, "Max": max_dim * 0.25, "Set length": 1},
        {"name": "bridge_offset", "type": "Continuous", "Min": 0, "Max": 1, "Set length": 1},
        {"name": "local_rot", "type": "Continuous", "Min": 0, "Max": 180, "Set length": 1},
    ] + _global_inputs(max_floors)


def _build_radial_inputs(max_dim: float, min_dim: float, max_floors: int) -> list[dict]:
    """16 genes: 12 shape (6 sectors x 2) + 4 global."""
    inputs = []
    for i in range(6):
        inputs.extend([
            {"name": f"sec{i}_on", "type": "Continuous", "Min": 0, "Max": 1, "Set length": 1},
            {"name": f"sec{i}_radius", "type": "Continuous", "Min": 0.2, "Max": 1.0, "Set length": 1},
        ])
    inputs.extend(_global_inputs(max_floors))
    return inputs


ALL_ALGORITHMS = [
    "additive", "subtractive", "grid",
    "lshape", "ushape", "cross", "courtyard",
    "tower_podium", "hshape", "radial",
]

_INPUT_BUILDERS = {
    "additive": _build_additive_inputs,
    "subtractive": _build_subtractive_inputs,
    "grid": _build_grid_inputs,
    "lshape": _build_lshape_inputs,
    "ushape": _build_ushape_inputs,
    "cross": _build_cross_inputs,
    "courtyard": _build_courtyard_inputs,
    "tower_podium": _build_tower_podium_inputs,
    "hshape": _build_hshape_inputs,
    "radial": _build_radial_inputs,
}


def build_default_job_spec(site_area_m2: float, constraints: list[dict],
                           building_type: str = "공동주택",
                           algorithm: str = "additive") -> dict:
    """
    Build a default GA job spec for mass optimization.

    10 algorithms supported. When algorithm="all", caller should
    iterate ALL_ALGORITHMS and build one spec per algorithm.
    """
    from backend.app.modules.design.generation.services.mass_evaluator import get_floor_height

    max_dim = math.sqrt(site_area_m2) * 0.9
    min_dim = max(3.0, max_dim * 0.1)

    max_height = 100.0
    for c in constraints:
        if c["name"] == "height" and c["Requirement"] == "Less than":
            max_height = c["val"]
            break

    floor_height = get_floor_height(building_type)
    max_floors = max(1, int(max_height / floor_height))

    input_builder = _INPUT_BUILDERS.get(algorithm, _build_additive_inputs)
    inputs = input_builder(max_dim, min_dim, max_floors)

    objectives = _TYPE_OBJECTIVES.get(building_type, _DEFAULT_OBJECTIVES)
    outputs = list(objectives) + constraints

    # SSIEA options — smaller budget when running "all" mode (caller adjusts)
    options = {
        "Number of generations": 120,
        "num_islands": 7,
        "pop_per_island": 30,
        "migration_interval": 8,
        "migrants_count": 3,
        "tournament_size": 8,
        "initial_mutation_rate": 0.35,
        "final_mutation_rate": 0.10,
        "algorithm": algorithm,
    }

    return {"inputs": inputs, "outputs": outputs, "options": options}


def compute_setback_geometry(site_polygon_geojson: dict, setback_m: float) -> dict | None:
    """
    Compute inward setback buffer polygon from site boundary.

    Returns GeoJSON polygon of the buildable area (site minus setback), or None.
    """
    from shapely.geometry import mapping
    from backend.app.modules.design.generation.services.site_geometry import geojson_to_polygon, wgs84_to_utm, utm_to_wgs84

    try:
        site_wgs = geojson_to_polygon(site_polygon_geojson)
        site_utm = wgs84_to_utm(site_wgs)
        setback_zone = site_utm.buffer(-setback_m)
        if setback_zone.is_empty or setback_zone.area < 1.0:
            return None
        setback_wgs = utm_to_wgs84(setback_zone)
        return mapping(setback_wgs)
    except Exception:
        return None


def build_floor_plan_spec(
    footprint,
    rooms_def: list[dict],
    cell_size: float = 3.0,
    num_generations: int = 50,
    population_size: int = 30,
    num_islands: int = 3,
) -> dict:
    """
    매스 footprint + rooms → floor plan GA job spec (Series gene).

    Args:
        footprint: Shapely Polygon (UTM coordinates)
        rooms_def: [{"name": str, "area": float, "adjacency": [str]}]
        cell_size: 그리드 셀 크기 (m)

    Returns:
        GA job spec dict compatible with SSIEAJob.
    """
    from backend.app.modules.design.generation.services.floor_packer import create_grid

    grid_info = create_grid(footprint, cell_size)
    num_cells = grid_info["rows"] * grid_info["cols"]
    num_rooms = len(rooms_def)

    return {
        "inputs_def": [{
            "type": "Series",
            "Set length": num_cells,
            "Depth": num_rooms + 1,
            "Mutation rate": 0.3,
        }],
        "outputs_def": [
            {"name": "adjacency_score", "type": "Objective", "Goal": "Max"},
            {"name": "area_error", "type": "Objective", "Goal": "Min"},
            {"name": "compactness", "type": "Objective", "Goal": "Max"},
        ],
        "options": {
            "num_generations": num_generations,
            "population_size": population_size,
            "num_islands": num_islands,
        },
        "grid_info": grid_info,
    }
