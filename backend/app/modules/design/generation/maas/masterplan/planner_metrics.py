"""Level metrics and feature helpers shared by the planner and its callers."""
from __future__ import annotations

from shapely.geometry import shape

from backend.app.modules.design.generation.maas.masterplan.geometry import feature, union_or_empty


def module_ideal_m2(rules):
    """Area per stall of the ideal double-loaded 90-degree module: stall + aisle + stall.

    The module, not the stall, is the unit of a parking layout, and area per stall is how the
    trade is judged (Chinese practice controls 单车指标 at 28-32 m2, US practice at 300-350 sf).
    With the snapshot's own dimensions this is stall_width * (2*stall_length + aisle_width) / 2;
    serving only one side of the aisle costs stall_width * (stall_length + aisle_width).
    """
    w = rules.get("stall_width_m"); l = rules.get("stall_length_m"); a = rules.get("aisle_width_m")
    if not (w and l and a):
        return None
    return {"double_loaded": w*(2*l+a)/2, "single_loaded": w*(l+a)}


SERVED_LAYERS = ("parking_stall", "parking_aisle", "vehicular_access")


def parking_entrance_feature(geometry, level, z):
    """A same-level connector does not by itself establish a ramp connection."""
    return feature('vehicular_access', geometry, level, z_m=z,
                   role='surface_entry_connector' if level == 0 else 'basement_entry_connector',
                   maneuver_status='needs_evidence')


def excavation_cost_units(area_m2, basement_levels):
    """Owner cost proxy: excavated plan area times depth count, in 10 m2 buckets."""
    return round(area_m2 * max(1, basement_levels) / 10.0)


def level_efficiency(features, rules):
    """Area per stall on each level, measured two ways, because they answer different questions.

    `area_per_stall_m2` divides the DRAWN parking area - the stalls, their aisle and the ramp
    landings that serve them - by the stalls.  It says how tight the rows are.

    `plate_area_per_stall_m2` divides the EXCAVATED slab, net of the declared non-parking
    programme, by the stalls.  It says what the basement cost.  These separate the moment a level
    carries fewer bands than its plate was cut for: a 1,270 m2 slab holding 20 cars reports 23.6 by
    the first measure and 63.5 by the second, and only the second is comparable to practice
    (reference ALT1 basement: 30.3 m2/stall) or to the published ladder (Kavanagh, The Parking
    Professional, IPMI 2015: 325 sf = 30.2 m2 as the planning constant).

    `over_module_ideal` - the number the ranking and the 2x advisory read - is therefore taken from
    the PLATE below grade and from the drawn area at and above it, where nothing is excavated.
    `over_module_ideal_basis` records which, so no reader has to guess.
    """
    ideal = module_ideal_m2(rules)
    by_level = {}
    for f in features:
        prop = f["properties"]; layer = prop.get("layer")
        if layer not in SERVED_LAYERS + ("basement_boundary", "basement_plant_zone"):
            continue
        entry = by_level.setdefault(prop.get("level", 0),
                                    {"stalls": 0, "served": [], "plate": [], "programme": []})
        geom = shape(f["geometry"])
        if layer in SERVED_LAYERS:
            entry["served"].append(geom)
            if layer == "parking_stall":
                entry["stalls"] += 1
        elif layer == "basement_boundary":
            entry["plate"].append(geom)
        else:
            entry["programme"].append(geom)
    out = {}
    for level, entry in by_level.items():
        if not entry["stalls"]:
            continue
        served = union_or_empty(entry["served"])
        per = served.area/entry["stalls"]
        row = {"stalls": entry["stalls"], "parking_area_m2": round(served.area, 2),
               "area_per_stall_m2": round(per, 2)}
        governing, basis = per, "drawn_parking_area"
        plate = union_or_empty(entry["plate"])
        if level < 0 and not plate.is_empty:
            programme = union_or_empty(entry["programme"])
            net = plate.difference(programme) if not programme.is_empty else plate
            if net.area > 0:
                row["plate_area_m2"] = round(net.area, 2)
                row["plate_area_per_stall_m2"] = round(net.area/entry["stalls"], 2)
                governing, basis = net.area/entry["stalls"], "excavated_plate"
        row["over_module_ideal"] = round(governing/ideal["double_loaded"], 2) if ideal else None
        row["over_module_ideal_basis"] = basis
        out[level] = row
    return out


def program_features(zone,level,z_m):
    """The reserved programme as drawing/handoff features: one zone plus the declared rooms."""
    if not zone:
        return []
    out=[feature("basement_plant_zone",zone["zone"],level,z_m=z_m,area_m2=zone["area_m2"],
                 declared_area_m2=zone["declared_area_m2"],side=zone["side"],depth_m=zone["depth_m"],
                 note="declared non-parking programme; room layout is the floor-plan agent's")]
    out.extend(feature("basement_room",r["polygon"],level,z_m=z_m,name=r["name"],kind=r["kind"],
                       declared_area_m2=r["area_m2"],placed_area_m2=r["placed_area_m2"]) for r in zone["rooms"])
    return out
