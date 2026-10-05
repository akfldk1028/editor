"""Bind a selected live Mass-owned source to a MasterPlan metric request.

No recipe execution, geometry repair, coordinate guessing or legal approval.
The source must already use the request's site-local XY frame. Ground contact
is an observed section, not proof of vehicle-height clearance under a mass.
"""
from __future__ import annotations

import copy
import math

from shapely.geometry import mapping, shape

from backend.app.modules.design.generation.maas.massv2.parcel_policy import source_plan_projection
from backend.app.modules.design.generation.maas.massv2.render_mesh import is_mesh_authoritative, mesh_plan_at
from backend.app.modules.design.generation.maas.source_geometry.ir import SourceMass
from backend.app.modules.design.generation.maas.masterplan.geometry import EPS, digest, polygon


def plan_request_from_mass(request, source, *, source_pnu, source_shape_id,
                           coordinate_crs, origin_utm, datum_m, shape_id_query=None):
    """Return a deep-copied request using actual selected mass geometry.

    SourceMass currently has no standard shape_id field. Supply the delivery
    owner's existing identity callable in `shape_id_query`; if a source exposes
    shape_id, that field must also match. No hash algorithm is copied here.
    `origin_utm` declares the source's existing local-frame origin, not an offset
    to apply. `datum_m` must equal the source owner's recorded ground datum.
    """
    if not isinstance(source, SourceMass):
        raise TypeError("a live selected SourceMass is required; serialized recipes are unsupported")
    if not source_pnu or str(source_pnu)!=str(request.get("pnu")):
        raise ValueError("mass source parcel does not match request pnu")
    if not coordinate_crs or coordinate_crs!=request.get("crs"):
        raise ValueError("mass source coordinate CRS does not match request")
    def origin(value):
        if (not isinstance(value,(list,tuple)) or len(value)!=2
                or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in value)):
            raise ValueError("mass source frame requires a finite explicit XY origin")
        return tuple(value)
    if origin(origin_utm)!=origin(request.get("origin_utm")):
        raise ValueError("mass source coordinate origin does not match request")
    recorded_datum=(source.metadata or {}).get("datum_m")
    if (isinstance(datum_m,bool) or not isinstance(datum_m,(int,float)) or not math.isfinite(datum_m)
            or isinstance(recorded_datum,bool) or not isinstance(recorded_datum,(int,float))
            or not math.isfinite(recorded_datum) or datum_m!=recorded_datum):
        raise ValueError("explicit datum must match the mass owner's recorded datum_m")
    if not isinstance(source_shape_id,str) or not source_shape_id.strip():
        raise ValueError("mass source identity must be explicit")
    stored_identity=getattr(source,"shape_id",None)
    if stored_identity is not None and stored_identity!=source_shape_id:
        raise ValueError("mass source identity field mismatch")
    if shape_id_query is not None:
        if not callable(shape_id_query) or shape_id_query(source)!=source_shape_id:
            raise ValueError("mass source identity query mismatch")
    elif stored_identity is None:
        raise ValueError("mass source identity requires its owner's query or shape_id field")

    projection,projection_basis=source_plan_projection(source)
    projection=polygon(projection,"mass source projection")
    authoritative=is_mesh_authoritative(source)
    ground=mesh_plan_at(source,datum_m) if authoritative else source.plan_at(datum_m)
    ground=polygon(ground,"mass source ground section")
    if not projection.buffer(EPS).covers(ground):
        raise ValueError("mass ground section lies outside its owner projection")
    for key,derived in (("footprint",projection),("ground_footprint",ground)):
        if request.get(key) is not None and shape(request[key]).symmetric_difference(derived).area>EPS:
            raise ValueError(f"authored {key} conflicts with selected mass source")
    result=copy.deepcopy(request)
    result.update(footprint=mapping(projection),ground_footprint=mapping(ground))
    pending=["mass_ground_vehicle_clearance_review","mass_structural_soffit_beams_services_review"]
    if not request.get("core"):
        pending.append("mass_semantic_core_geometry_missing")
    if not (request.get("evidence") or {}).get("columns"):
        pending.append("mass_structural_column_geometry_unverified")
    result["mass_source_pending_reviews"]=list(dict.fromkeys([
        *(request.get("mass_source_pending_reviews") or []),*pending]))
    record={"schema_version":"arr.masterplan.mass_source_binding.v1",
        "source_pnu":str(source_pnu),"source_shape_id":source_shape_id,
        "coordinate_crs":coordinate_crs,"origin_utm":list(origin_utm),"datum_m":datum_m,
        "coordinate_frame":"site-local metres: crs minus origin_utm",
        "projection_basis":projection_basis,
        "ground_basis":"authoritative_mesh_section" if authoritative else "source_mass_plan_at",
        "geometry_hash":digest({"footprint":result["footprint"],"ground_footprint":result["ground_footprint"]}),
        "identity_basis":"owner_shape_id_query" if shape_id_query is not None else "source_shape_id_field",
        "pending_reviews":list(pending),
        "scope":"selected source projection and observed ground section; no structural or legal approval"}
    result["evidence"]=dict(result.get("evidence") or {})
    result["evidence"]["mass_geometry"]=record
    return result


__all__=["plan_request_from_mass"]
