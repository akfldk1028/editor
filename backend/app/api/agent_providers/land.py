"""Pass-through endpoints for the agents (SiteContextAgent, Lawagent), which no longer import land.services in-process.

Each view returns what the service function returns, so the agents' contracts did not move - only the transport did
(agents reach ARR over HTTP, never through sys.path). Kept out of views.py on purpose: this is the agent seam, not
the frontend API. Failures are dicts too ({"success": False, "error": ...}) so callers keep one shape.

    POST /land/parcel-geometry/   {pnu}                      -> pnu_resolver.fetch_parcel_geometry
    POST /land/roads/             {geometry}                 -> road_frontage.fetch_neighbor_roads
    POST /land/datum/             {pnu | polygon, road_centerline?, neighbor_polygon?,
                                   apply_road_datum?, apply_86_neighbor_avg?}
                                                             -> asdict(compute_datum_elevation(DatumContext(...))) + case
    POST /land/basement-storey/   {datum_m, floor_level_m, storey_height_m, perimeter_bands?}
                                                             -> datum.calculator.basement_storey_test
"""
import json
from dataclasses import asdict

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from backend.app.modules.land.reference.services import pnu_resolver, road_frontage


def _body(request):
    try:
        body = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    return body if isinstance(body, dict) else None


def _bad(message, **extra):
    return JsonResponse({"success": False, "error": message, **extra}, status=400)


def _failed(exc):
    """An engine or network failure is reported, never turned into a guessed value."""
    return JsonResponse({"success": False, "error": f"{type(exc).__name__}: {exc}"}, status=502)


def _geojson_polygon(value, name):
    """A GeoJSON Polygon/MultiPolygon as one shapely polygon; a MultiPolygon keeps its largest ring."""
    from shapely.geometry import shape
    if not isinstance(value, dict) or value.get("type") not in ("Polygon", "MultiPolygon"):
        raise ValueError(f"{name} must be a GeoJSON Polygon or MultiPolygon")
    geom = shape(value)
    if geom.geom_type == "MultiPolygon":
        geom = max(geom.geoms, key=lambda g: g.area)
    if geom.is_empty or not geom.is_valid:
        raise ValueError(f"{name} is empty or invalid")
    return geom


@csrf_exempt
@require_http_methods(["POST"])
def parcel_geometry(request):
    body = _body(request)
    if body is None:
        return _bad("Invalid JSON", geometry=None)
    pnu = str(body.get("pnu") or "").strip()
    if not pnu:
        return _bad("pnu is required", geometry=None)
    return JsonResponse(pnu_resolver.fetch_parcel_geometry(pnu))


@csrf_exempt
@require_http_methods(["POST"])
def roads(request):
    body = _body(request)
    if body is None:
        return _bad("Invalid JSON", roads=[])
    geometry = body.get("geometry")
    if not isinstance(geometry, dict):
        return _bad("geometry (a GeoJSON object) is required", roads=[])
    return JsonResponse(road_frontage.fetch_neighbor_roads(geometry))


@csrf_exempt
@require_http_methods(["POST"])
def datum(request):
    """Statutory ground surface (건축법 시행령 제119조제2항) by the datum engine. The caller grades the evidence."""
    body = _body(request)
    if body is None:
        return _bad("Invalid JSON")
    pnu = str(body.get("pnu") or "").strip()
    polygon = body.get("polygon")
    if not pnu and polygon is None:
        return _bad("give pnu or polygon")
    try:
        from shapely.geometry import shape
        from backend.app.modules.land.reference import config as land_config
        from backend.app.modules.land.reference.services.datum import DatumContext, compute_datum_elevation
        if polygon is not None:
            parcel, geometry_source = _geojson_polygon(polygon, "polygon"), "caller_polygon"
        else:
            fetched = pnu_resolver.fetch_parcel_geometry(pnu)
            if not fetched.get("success") or not isinstance(fetched.get("geometry"), dict):
                return JsonResponse({"success": False, "pnu": pnu, "missing_evidence": ["parcel_geometry"],
                                     "error": fetched.get("error") or "parcel geometry unavailable"}, status=404)
            parcel, geometry_source = _geojson_polygon(fetched["geometry"], "parcel geometry"), "vworld_cadastre"
        road = body.get("road_centerline")
        neighbour = body.get("neighbor_polygon")
        result = compute_datum_elevation(DatumContext(
            parcel_wgs=parcel,
            road_centerline_wgs=shape(road) if isinstance(road, dict) else None,
            neighbor_parcel_wgs=_geojson_polygon(neighbour, "neighbor_polygon") if neighbour is not None else None,
            apply_86_neighbor_avg=bool(body.get("apply_86_neighbor_avg", False)),
            apply_road_datum=bool(body.get("apply_road_datum", False))))
    except ValueError as exc:
        return _bad(str(exc))
    except Exception as exc:
        return _failed(exc)
    out = asdict(result)
    out.update({"success": True, "case": result.case.value, "geometry_source": geometry_source,
                "parcel_vertex_count": len(parcel.exterior.coords),
                "elevation_provider_configured": land_config.ELEVATION_PROVIDER})
    return JsonResponse(out, json_dumps_params={"default": str})


@csrf_exempt
@require_http_methods(["POST"])
def basement_storey(request):
    """Is the storey a 지하층 (건축법 제2조제1항제5호)? basement_storey_test, verbatim."""
    body = _body(request)
    if body is None:
        return _bad("Invalid JSON")
    try:
        from backend.app.modules.land.reference.services.datum.calculator import basement_storey_test
        args = [float(body[k]) for k in ("datum_m", "floor_level_m", "storey_height_m")]
    except KeyError as exc:
        return _bad(f"{exc.args[0]} is required")
    except (TypeError, ValueError):
        return _bad("datum_m, floor_level_m and storey_height_m must be numbers")
    bands = body.get("perimeter_bands")
    if bands is not None and not isinstance(bands, list):
        return _bad("perimeter_bands must be a list of {datum_m, length_m}")
    try:
        out = basement_storey_test(*args, bands)
    except ValueError as exc:
        return _bad(str(exc))
    except Exception as exc:
        return _failed(exc)
    if isinstance(out, dict):
        out.setdefault("success", True)
        return JsonResponse(out, json_dumps_params={"default": str})
    return JsonResponse({"success": True, "result": out}, json_dumps_params={"default": str})
