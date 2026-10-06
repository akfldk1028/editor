"""Basement programme checks for `validation.validate_plan`."""
from __future__ import annotations

from shapely.ops import unary_union

from backend.app.modules.design.generation.maas.masterplan.compact_slab import REQUIRED_LAYERS
from backend.app.modules.design.generation.maas.masterplan.validation_geometry import TOL


def _check_basement_programme(check, grouped, request, placement_stage, source_obstacles):
    # The declared basement programme keeps its area: stalls may not stand in the reserved zone and
    # the zone must hold what was declared (제6조 dimensions are checked elsewhere; this is the brief).
    declared_program=(request.get("options") or {}).get("basement_program") or []
    basement_levels={level for (level,layer),items in grouped.items() if level<0 and items and layer=="basement_boundary"}
    used_basement_levels={level for (level,layer),items in grouped.items() if level<0 and items and layer in REQUIRED_LAYERS}
    for level in sorted(used_basement_levels):
        check(f"basement_boundary_present:{level}",level in basement_levels)
    basement_levels |= used_basement_levels
    if declared_program and basement_levels:
        programme_level=max(basement_levels)
        if placement_stage:
            check(f"basement_programme_present:{programme_level}",bool(grouped[(programme_level,"basement_plant_zone")]))
        else:
            check(f"basement_programme_present:{programme_level}",bool(grouped[(programme_level,"basement_plant_zone")])
                  and bool(grouped[(programme_level,"basement_room")]))
    programme_levels={level for (level,layer),items in grouped.items() if items
                      and layer in {"basement_plant_zone","basement_room"}}
    for level in sorted(programme_levels):
        items=grouped[(level,"basement_plant_zone")]
        zone=unary_union([g for g,p in items]); declared=sum(float(p.get("declared_area_m2") or 0) for g,p in items)
        clash=[p.get("stall_id") for g,p in grouped[(level,"parking_stall")] if g.intersection(zone).area>TOL]
        check(f"plant_zone_clear:{level}",not clash,stalls_in_zone=clash[:5],level=level)
        check(f"plant_zone_area:{level}",zone.area+TOL>=declared,reserved_m2=round(zone.area,2),declared_m2=round(declared,2))
        programme_blockers=unary_union([*source_obstacles,*[g for g,p in grouped[(level,"building_core")]
            +grouped[(level,"column")]+grouped[(level,"ramp")]]])
        check(f"plant_zone_obstructions:{level}",zone.intersection(programme_blockers).area<=TOL)
        individual_rooms=grouped[(level,"basement_room")]
        for index,(room,props) in enumerate(individual_rooms):
            check(f"basement_room_zone_containment:{level}:{index}",zone.buffer(TOL).covers(room))
            if props.get("declared_area_m2") is not None:
                check(f"basement_room_declared_area:{level}:{index}",room.area+TOL>=props["declared_area_m2"])
            check(f"basement_room_overlap:{level}:{index}",all(room.intersection(other).area<=TOL
                for other,_ in individual_rooms[index+1:]))
            check(f"basement_room_connected:{level}:{index}",room.geom_type=="Polygon" and not room.interiors)
            check(f"basement_room_obstructions:{level}:{index}",room.intersection(programme_blockers).area<=TOL)
        if not placement_stage:
            requested = {}
            for room in (request.get("options") or {}).get("basement_program") or []:
                name=str(room.get("name") or "unnamed")
                requested[name]=requested.get(name,0)+float(room["area_m2"])
            for name, area in requested.items():
                pieces=[g for g,p in grouped[(level,"basement_room")] if p.get("name")==name]
                actual=unary_union(pieces)
                check(f"basement_room_area:{level}:{name}",actual.area+TOL>=area,
                      placed_m2=round(actual.area,2),declared_m2=area)
                check(f"basement_room_containment:{level}:{name}",zone.buffer(TOL).covers(actual))
