"""Source-preserved mass-search defaults; these bounds are not legal permissions."""
import math

FLOOR_HEIGHTS = {'공동주택': 2.8, '근린생활시설': 3.5, '업무시설': 3.8, '판매시설': 4.0, '숙박시설': 3.0, '문화집회시설': 4.5, '의료시설': 3.6, '교육연구시설': 3.5, '공장': 5.0, '창고시설': 6.0}

def get_floor_height(building_type):
    return FLOOR_HEIGHTS.get(building_type, 3.0)

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
