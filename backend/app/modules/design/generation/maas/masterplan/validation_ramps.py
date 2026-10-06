"""Per-ramp checks for `validation.validate_plan`: endpoints, run, width, radius, grade, headroom."""
from __future__ import annotations

import math

from shapely.geometry import Point, shape
from shapely.ops import unary_union

from backend.app.modules.design.generation.maas.masterplan.ramp_overhead import overhead_clearance
from backend.app.modules.design.generation.maas.masterplan.validation_geometry import TOL, _flat_ramp_area, _min_turn_radius


def _check_ramps(check, pending, grouped, request, rules, site, source_obstacles, ground_occupancy):
    ramps = [(g,p) for (level,layer),items in grouped.items() if layer=="ramp" for g,p in items]
    for g,p in ramps:
        rid = f"{p.get('from_level')}:{p.get('to_level')}"
        profile = p.get("profile",[])
        if p.get('from_level',0)<0:
            pending.append('stacked_ramp_soffit_beams_services_review')
        center=next((c for c,cp in grouped[(p.get("to_level"),"ramp_centerline")]
            if cp.get("from_level")==p.get("from_level") and cp.get("to_level")==p.get("to_level")),None)
        for endpoint,role,level in ((0,"ramp_departure",p.get("from_level")),
                                    (-1,"ramp_arrival",p.get("to_level"))):
            access=unary_union([a for a,ap in grouped[(level,"vehicular_access")]
                if ap.get("role")==role and ap.get("from_level",p.get("from_level"))==p.get("from_level")
                and ap.get("to_level",p.get("to_level"))==p.get("to_level")])
            flat=_flat_ramp_area(grouped,g,p,level)
            valid_endpoint=False
            if center is not None and center.geom_type=="LineString" and profile:
                point=center.coords[endpoint]
                valid_endpoint=(len(point)>=3 and abs(point[2]-profile[endpoint]["z_m"])<=TOL
                    and access.buffer(TOL).covers(Point(point[:2]))
                    and access.intersection(flat).area>TOL)
            check(f"{role}_profile_endpoint:{rid}",valid_endpoint)
        # A ramp is only partly below grade: its upper landing and the top of its slope sit at or
        # near ground level and legitimately lie beyond the parking plate. The binding limit is the
        # PARCEL, and that the dig drawn for the level contains it - which the envelope check above
        # enforces from the other side.
        check(f"ramp_containment:{rid}",site.buffer(TOL).covers(g))
        curved = str(p.get("layout_type","")).startswith("curved")
        if curved:
            # A turning ramp is not its bounding rectangle: measure the run along the centreline
            # the plan actually carries, the band width as area over that run, and the sharpest
            # turn from the centreline itself (제6조제1항제5호나목·다목).
            spine = next((c for c,cp in grouped[(p.get("to_level"),"ramp_centerline")]
                          if cp.get("from_level")==p.get("from_level")),None)
            run = spine.length if spine is not None else 0.0
            measured_width = g.area/run if run > TOL else 0.0
            check(f"ramp_profile_length:{rid}",bool(profile) and abs(profile[0]["distance_m"])<=TOL and
                  run > TOL and abs(profile[-1]["distance_m"]-run)<=0.5,centreline_run_m=round(run,2))
            need_w = rules.get("curved_ramp_width_m") or rules.get("ramp_width_m")
            if need_w:
                # the band is a polygonal approximation of an arc, so its area is a few parts in
                # 10,000 under the true annulus: 10 mm of tolerance, not the geometric TOL
                check(f"ramp_width:{rid}",measured_width+0.01>=need_w,measured_width_m=round(measured_width,3),required_m=need_w)
            inner_min = rules.get("curve_min_inner_radius_m")
            if inner_min is not None and spine is not None:
                turn = _min_turn_radius([(c[0],c[1]) for c in spine.coords])
                inner = (turn - measured_width/2) if turn is not None else None
                check(f"ramp_curve_radius:{rid}",inner is not None and inner+TOL>=float(inner_min),
                      measured_centreline_radius_m=None if turn is None else round(turn,2),
                      measured_inner_radius_m=None if inner is None else round(inner,2),required_inner_m=inner_min)
        else:
            rectangular = g.minimum_rotated_rectangle
            edges = [math.dist(a,b) for a,b in zip(rectangular.exterior.coords,list(rectangular.exterior.coords)[1:])]
            check(f"ramp_profile_length:{rid}",bool(profile) and abs(profile[0]["distance_m"])<=TOL and
                  abs(profile[-1]["distance_m"]-max(edges))<=TOL)
            if rules.get("ramp_width_m"):
                check(f"ramp_width:{rid}",min(edges)+TOL>=rules["ramp_width_m"])
        valid = len(profile)>=2
        grades=[]
        for a,b in zip(profile,profile[1:]):
            dx=b["distance_m"]-a["distance_m"]
            if dx<=0:
                valid=False
            else:
                grades.append(abs(b["z_m"]-a["z_m"])/dx)
        maximum=(rules.get("curved_ramp_max_slope") if curved else None) or rules.get("ramp_max_slope")
        if curved and grades and p.get("radius_m") and p.get("width_m"):
            # On an arc the rise is fixed and the path at radius r is r*theta, so the grade scales
            # as 1/r. IStructE measures a curved ramp's gradient ON THE CENTRE LINE; Weant measures
            # it along the outer edge; 시행규칙 제6조제1항제5호라목 does not say. The profile here is
            # the centre line, so the kerb figures are reported, not judged.
            R=float(p["radius_m"]); half=float(p["width_m"])/2
            worst=max(grades)
            pending.append(f"curved_ramp_grade_datum:{rid}")
            check(f"ramp_grade_kerbs:{rid}",None,note="the datum is unsettled: IStructE measures on the "
                  "centre line, Weant on the outer edge, and 시행규칙 제6조제1항제5호라목 is silent",
                  centreline_grade=round(worst,4),
                  inner_kerb_grade=round(worst*R/(R-half),4) if R>half else None,
                  outer_kerb_grade=round(worst*R/(R+half),4))
        check(f"ramp_grade:{rid}",valid and maximum is not None and max(grades,default=0)<=maximum+TOL,
              max_grade=max(grades,default=None))
        floor_h=request.get("options",{}).get("basement_floor_height_m")
        if floor_h is not None and profile:
            check(f"ramp_level_rise:{rid}",abs(profile[0]["z_m"]-p["from_level"]*floor_h)<=TOL and
                  abs(profile[-1]["z_m"]-p["to_level"]*floor_h)<=TOL)
        headroom = (floor_h or 0)-request.get("options",{}).get("slab_depth_m",0)
        if rules.get("min_headroom_m"):
            check(f"ramp_stacking_headroom:{rid}",headroom+TOL>=rules["min_headroom_m"],clear_height_m=headroom)
        cores = unary_union(source_obstacles)
        check(f"ramp_obstructions:{rid}",g.intersection(cores).area<=TOL)
        if p.get("overhead_soffit_z_m") is not None:
            slab_depth=request.get("options",{}).get("slab_depth_m")
            soffit=p["overhead_soffit_z_m"]
            source_ok=(isinstance(slab_depth,(int,float)) and not isinstance(slab_depth,bool)
                and math.isfinite(slab_depth) and isinstance(soffit,(int,float))
                and math.isfinite(soffit) and abs(soffit+slab_depth)<=TOL)
            check(f"ramp_overhead_soffit_source:{rid}",source_ok)
            center=next((c for c,cp in grouped[(p.get("to_level"),"ramp_centerline")]
                if cp.get("from_level")==p.get("from_level") and cp.get("to_level")==p.get("to_level")),None)
            occupied=ground_occupancy if ground_occupancy is not None else unary_union(
                [geometry for geometry,props in grouped[(0,"building_footprint")]])
            clearance=None
            profile_matches=False
            if center is not None and center.geom_type=="LineString" and profile:
                coords=list(center.coords)
                station=0.0
                profile_matches=all(len(c)>=3 and math.isfinite(c[2]) for c in coords)
                for index,c in enumerate(coords):
                    if index:
                        station+=math.dist(coords[index-1][:2],c[:2])
                    segment=next(((a,b) for a,b in zip(profile,profile[1:])
                        if a["distance_m"]-TOL<=station<=b["distance_m"]+TOL
                        and b["distance_m"]>a["distance_m"]),None)
                    if segment is None or len(c)<3:
                        profile_matches=False
                        break
                    a,b=segment
                    z=a["z_m"]+(station-a["distance_m"])/(b["distance_m"]-a["distance_m"])*(b["z_m"]-a["z_m"])
                    profile_matches=profile_matches and abs(c[2]-z)<=TOL
            check(f"ramp_overhead_xyz_profile:{rid}",profile_matches)
            if source_ok and profile_matches and rules.get("min_headroom_m") and p.get("width_m"):
                try:
                    clearance=overhead_clearance({"centerline":center,"width_m":p["width_m"]},
                        occupied,-slab_depth,rules["min_headroom_m"])
                except (ValueError,TypeError):
                    clearance=None
            check(f"ramp_overhead_clearance:{rid}",bool(clearance and clearance["passed"]),
                  minimum_clearance_m=clearance["minimum_clearance_m"] if clearance else None)
            pending.append("structural_soffit_beams_services_review")
        if p.get("from_level")==0 and request.get("frontage"):
            # The ramp reaches the road directly, or through the ground drive it departs from
            # (row-and-aisle plans: the ramp leaves the through aisle), which must itself meet the road.
            road=shape(request["frontage"])
            ground_drive=unary_union([gg for gg,pp in grouped[(0,"parking_aisle")]+grouped[(0,"vehicular_access")]])
            via_drive=(not ground_drive.is_empty and g.distance(ground_drive)<=TOL and ground_drive.distance(road)<=TOL)
            check("ramp_road_connection",g.distance(road)<=TOL or via_drive)
