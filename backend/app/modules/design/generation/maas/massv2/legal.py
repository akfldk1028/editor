"""The parcel's own limits, fetched once and handed to the form language.

This adapter combines the existing legal stack (Vworld boundary, zoning,
setbacks, sunlight, and legal floor fields) with source-registered parcel plan
controls owned by parcel_policy. Cartographic registration is reported as such;
it is not a measured survey or complete permit assessment.

There is no synthetic fallback. A parcel that cannot be resolved raises, rather
than quietly handing back a rectangle that would make every downstream number
meaningless.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from types import SimpleNamespace
from typing import Any

from shapely.affinity import translate
from shapely.geometry import LineString, Polygon

from backend.app.modules.design.generation.maas.book_language.downstream_hard_gate import LegalGenerationContext, build_legal_generation_context, generation_site_at_height
from backend.app.modules.design.generation.maas.book_language.legal_floor_field import materialize_legal_floor_field
from backend.app.modules.design.generation.services.constraint_bridge import regulations_to_constraints
from backend.app.modules.land.reference import config as land_config
from backend.app.modules.design.generation.services.site_geometry import fetch_parcel_boundary, geojson_to_polygon, wgs84_to_utm
from backend.app.modules.design.generation.maas.massv2.parcel_policy import policy_of, default_building_type, registered_buildable, frontage_evidence
from backend.app.modules.land.reference.services.zone_split import SPLIT_VERSION, exclusive_zone_names, with_removed


logger = logging.getLogger(__name__)


class LegalSiteUnavailable(RuntimeError):
    """The parcel could not be resolved from live data."""


def apply_registered_parcel_plan(pnu, parcel, context, *, parcel_policy=True):
    """Intersect the existing legal context with source-registered plan controls."""
    site = SimpleNamespace(pnu=pnu, site_local_utm=parcel, parcel_policy=parcel_policy)
    try:
        registered = registered_buildable(site)
    except ValueError as error:
        raise LegalSiteUnavailable(str(error)) from error
    if registered is None:
        return context
    buildable = context.generation_site.intersection(registered)
    if context.envelope.buildable_footprint is not None:
        buildable = buildable.intersection(context.envelope.buildable_footprint)
    if buildable.is_empty:
        raise LegalSiteUnavailable('registered building line leaves no generation site')
    return replace(context,
        envelope=replace(context.envelope, buildable_footprint=buildable),
        generation_site=buildable,
        evidence={**context.evidence, 'generation_site_area_m2': round(buildable.area, 3),
                  'frontage_constraints': frontage_evidence(site)})


@dataclass(frozen=True)
class LegalSite:
    """Everything the form language needs to know about one parcel."""

    pnu: str
    site_local_utm: Polygon
    site_origin_utm: tuple[float, float]
    context: LegalGenerationContext
    floor_field: dict[str, Any]
    # Boundary segments a neighbouring parcel is built against, in the same
    # site-local frame as everything else. What is left of the boundary is the
    # side the parcel is open on - see `siting.open_side_direction`.
    shared_edges: tuple[tuple[tuple[float, float], ...], ...] = ()
    # What is being built. It reached the capacity calculation and stopped
    # there, so every gate downstream judged a 근린생활시설 by rules written
    # for a dwelling - see `plausibility.daylight_is_required_for`.
    building_type: str | None = None
    # Which ground plane the envelope was measured from. The datum computation
    # falls back to a flat 0 m when it cannot read an elevation, and the run
    # sheet had no way to tell that apart from a parcel that is genuinely flat:
    # the Uijeongbu parcel sits 25.5 km north of the only DEM on this machine,
    # so every grid so far was measured on the fallback while the flag read on.
    datum: dict[str, Any] | None = None
    # The regulation the caps came from (regulation_calculator.calculate_all): which
    # articles, which ordinance edition, on which assessment date. Kept so a receipt
    # can cite them instead of only the numbers.
    regulation: dict[str, Any] | None = None
    # How the parcel was divided between its 용도지역 for 제84조 (zone_split.ZoneSplit.to_dict() plus
    # `removed_zones`): which hair-thin strips were excluded as boundary tolerance and disclosed.
    zone_split: dict[str, Any] | None = None
    # Whether the hand-registered parcel table (parcel_policy._POLICIES) narrows this parcel. Mass generation keeps
    # it; the law parcel-limits answer turns it off so its caps come from public rules alone.
    parcel_policy: bool = True

    def __post_init__(self):
        object.__setattr__(self, 'building_type', default_building_type(self.pnu if self.parcel_policy else None, self.building_type))

    @property
    def datum_is_measured(self) -> bool:
        """Did an elevation source actually answer for this parcel."""

        return bool(self.datum) and self.datum.get("elevation_source") not in (
            None, "failed",
        )

    @property
    def parcel_area_m2(self) -> float:
        return float(self.site_local_utm.area)

    @property
    def ground_capacity_m2(self) -> float:
        """건축면적 ceiling - 건축법 시행령 제119조 제1항 제2호."""

        measured = float(self.floor_field.get("bcr_footprint_capacity_m2") or 0.0)
        cap = (policy_of(self) or {}).get('max_bcr_pct')
        return min(measured, self.parcel_area_m2 * cap / 100) if cap is not None else measured

    @property
    def far_capacity_m2(self) -> float:
        measured = float(self.floor_field.get("statutory_far_capacity_m2") or 0.0)
        cap = (policy_of(self) or {}).get('max_far_pct')
        return min(measured, self.parcel_area_m2 * cap / 100) if cap is not None else measured

    @property
    def max_storeys(self):
        return (policy_of(self) or {}).get('max_storeys')

    @property
    def statutory_max_height_m(self):
        return (policy_of(self) or {}).get('statutory_max_height_m')

    @property
    def floor_height_m(self) -> float:
        return float(getattr(self.context.envelope, "floor_height", 0.0) or 0.0)

    def plan_at(self, height_m: float) -> Polygon | None:
        """The legal footprint at a height, already sunlight-clipped.

        The parcel does not change during a run, so this is a lookup rather
        than a computation. It was being recomputed 21,537 times over the
        seventy-six authored sentences - a quarter of the whole runtime - for
        a few hundred distinct heights, because every fit and every compile
        asks each band where its ceiling is.
        """

        key = float(height_m)
        cache = self.__dict__.get("_plan_at_cache")
        if cache is None:
            cache = {}
            object.__setattr__(self, "_plan_at_cache", cache)
        if key not in cache:
            plan = generation_site_at_height(self.context, key)
            registered = registered_buildable(self)
            if registered is not None and plan is not None:
                plan = plan.intersection(registered)
                if plan.is_empty:
                    plan = None
            cache[key] = plan
        return cache[key]

    def evidence(self) -> dict[str, Any]:
        from backend.app.modules.design.generation.maas.massv2.siting import site_open_side_evidence
        frontages = frontage_evidence(self)
        return {
            "schema_version": "arr.maas.massv2_legal_site.v1",
            "pnu": self.pnu,
            "parcel_area_m2": round(self.parcel_area_m2, 2),
            "ground_capacity_m2": round(self.ground_capacity_m2, 3),
            "far_capacity_m2": round(self.far_capacity_m2, 3),
            "floor_height_m": self.floor_height_m,
            'max_storeys': self.max_storeys,
            'statutory_max_height_m': self.statutory_max_height_m,
            'building_type': self.building_type,
            'parcel_policy': policy_of(self),
            'datum_measured': self.datum_is_measured,
            'exact_building_line_geometry_verified': False,
            'building_line_geometry_registered': frontages is not None,
            'frontage_constraints': frontages,
            'zone_split': self.zone_split,
            'authoring_frontage': site_open_side_evidence(self),
            "legal_floor_section_count": len(
                self.floor_field.get("legal_floor_section_areas_m2") or ()
            ),
        }


def _read_zoning_cache(path) -> dict | None:
    """The cached zoning answer for a parcel, only when it was written by the current split rule
    (`split_version`); an older file is ignored and rewritten, so a rule change reaches every parcel."""
    import json as _json

    if not path.exists():
        return None
    try:
        payload = _json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("split_version") != SPLIT_VERSION:
        logger.info("zoning cache %s has split_version %r, recomputing", path.name, payload.get("split_version"))
        return None
    return payload


def _write_zoning_cache(path, pnu: str, land_info: dict, areas: dict[str, float], split_detail: dict | None) -> None:
    import json as _json

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_json.dumps({"pnu": pnu, "land_info": land_info, "areas": areas, "zone_split": split_detail,
                                     "split_version": SPLIT_VERSION}, ensure_ascii=False, indent=1), encoding="utf-8")
    except (OSError, TypeError, ValueError):
        pass


def load_legal_site(pnu: str, *, building_type: str | None = None, assessment_date: str | None = None,
                    parcel_policy: bool = True) -> LegalSite:
    """Resolve one parcel into the limits the form language generates against."""

    building_type = default_building_type(pnu if parcel_policy else None, building_type)
    boundary = fetch_parcel_boundary(pnu)
    if boundary is None:
        raise LegalSiteUnavailable(
            f"Vworld parcel boundary is required for {pnu}; synthetic fallback is not allowed"
        )

    from backend.app.modules.land.reference.services import land_api, regulation_calculator, road_frontage, zoning_mapper
    from backend.app.modules.land.reference.services.setback_geometry import compute_setback_lines

    # Zoning is static and the certificate of every judged mass carries the
    # limits derived from it. One Vworld timeout on 2026-09-10 answered with
    # the land-use list missing, the area-weighted FAR moved from 249.7094%
    # to 249.67%, and every seat on the board - and every anchor - stopped
    # matching its certificate. A complete answer is kept beside the parcel
    # boundary cache and is the answer from then on; delete the file to refresh.
    from backend.app.modules.design.generation.services.site_geometry import PARCEL_BOUNDARY_CACHE_DIR
    zoning_cache = PARCEL_BOUNDARY_CACHE_DIR / f"{pnu}.zoning.json"
    cached_zoning = _read_zoning_cache(zoning_cache)
    if cached_zoning is not None:
        land_info = cached_zoning["land_info"]
    else:
        land_info = land_api.get_land_use_info(pnu)
    zones = land_info.get("zones") or []
    # 국토계획법 제84조: a parcel across two 용도지역 is governed by how much of it
    # is in each, so the split is measured before the limits are asked for. It is
    # only fetched when there is more than one zone to split between, and a
    # failure to measure is not fatal here - `resolve_limits` answers with
    # `needs_zone_areas` and the site refuses itself below, rather than this
    # quietly substituting a guess. What the measurement excluded (a hair of
    # another zone at the boundary) travels with the site as `zone_split`.
    areas: dict[str, float] = {}
    split_detail: dict[str, Any] | None = None
    if cached_zoning is not None:
        areas = {str(k): float(v) for k, v in (cached_zoning.get("areas") or {}).items()}
        split_detail = cached_zoning.get("zone_split") if isinstance(cached_zoning.get("zone_split"), dict) else None
    elif sum(zoning_mapper.lookup(zone) is not None for zone in zones) > 1:
        # Only a parcel across two 용도지역 needs the split; 지구·구역 names in the list are not zones.
        from backend.app.modules.land.reference.services import zone_geometry

        try:
            split = zone_geometry.parcel_zone_split(
                geojson_to_polygon(boundary), to_utm=wgs84_to_utm
            )
            areas, split_detail = dict(split.areas), split.to_dict()
        except zone_geometry.ZoneGeometryUnavailable as error:
            # 국토계획법 제84조 apportions a parcel that straddles zones by the
            # area in each. Without the split there is no lawful way to combine
            # them, and carrying on took the permissive side: with the Vworld
            # key expired this parcel came back as 2,000 m2 of 건폐 and 32,496
            # m2 of 용적 against its real 1,498 and 6,242, and every mass built
            # on that would have been certified lawful against a site that does
            # not exist. Missing zoning is missing, like the boundary above.
            raise LegalSiteUnavailable(
                f"{pnu} straddles {len(zones)} zones and the area split is "
                f"unavailable ({error}); 제84조 needs the areas"
            ) from error
    if (cached_zoning is None and land_info.get("success") and zones
            and not land_info.get("errors") and (len(zones) == 1 or areas)):
        _write_zoning_cache(zoning_cache, pnu, land_info, areas, split_detail)
    # A 용도지역 the split left no ground to (a strip excluded as boundary tolerance) is not a part of
    # this parcel for 제84조: it leaves the zone list, and the exclusion is disclosed in `zone_split`.
    kept_zones, removed_zones = exclusive_zone_names(
        areas if split_detail is not None else None, zones, lambda name: zoning_mapper.lookup(name) is not None,
        uncovered_m2=float((split_detail or {}).get("uncovered_m2") or 0.0), parcel_area_m2=(split_detail or {}).get("parcel_area_m2"))
    zone_split_payload = with_removed(split_detail, removed_zones) if split_detail is not None else None
    limits = zoning_mapper.resolve_limits(kept_zones, areas) if kept_zones else {}
    zone_names = [
        item["zone_name"] if isinstance(item, dict) else str(item)
        for item in ((limits or {}).get("zones") or kept_zones)
    ]
    if not zone_names:
        raise LegalSiteUnavailable(f"{pnu} zoning lookup returned no executable zone")

    regulation = regulation_calculator.calculate_all(
        zone_names,
        land_info=land_info,
        sigungu_code=pnu[:5],
        zone_areas=areas,
        use_llm_extraction=False,
        # The caller's 기준일 (the law screen's), else the calculator's default (the server's date).
        **({'assessment_date': assessment_date} if assessment_date else {}),
    )
    try:
        constraints = regulations_to_constraints(regulation)
    except ValueError as exc:
        raise LegalSiteUnavailable(f"{pnu}: {exc}") from exc
    if not constraints:
        raise LegalSiteUnavailable(f"{pnu} regulation lookup returned no constraints")

    roads = road_frontage.fetch_neighbor_roads(boundary)
    neighbors = road_frontage.fetch_neighbor_parcels(boundary)
    setback_lines = compute_setback_lines(
        boundary,
        regulation,
        # §119 datum, on when the deployment has an elevation source. The web
        # path already reads this flag; the mass path hardcoded False, so every
        # scheme was measured from a flat ground whatever the site did. On a
        # 15 m 기복 parcel that is not a rounding difference, it is the wrong
        # ground plane. Where no elevation is available the datum computation
        # reports its own failure and the envelope falls back as before.
        compute_datum=land_config.ENABLE_DATUM_ELEVATION,
        road_frontages=(roads.get("roads") or []) if isinstance(roads, dict) else [],
        neighbor_parcels=(neighbors.get("neighbors") or []) if isinstance(neighbors, dict) else [],
    )

    site_utm = wgs84_to_utm(geojson_to_polygon(boundary))
    min_x, min_y = site_utm.bounds[0], site_utm.bounds[1]
    # Generation happens in a site-local frame. UTM northings are seven digits,
    # and doing form arithmetic against those spends float precision on an
    # offset that means nothing to the design.
    local_site = translate(site_utm, xoff=-min_x, yoff=-min_y)

    context = build_legal_generation_context(
        site_local_utm=local_site,
        site_origin_utm=(min_x, min_y),
        building_type=building_type,
        constraints=constraints,
        sunlight_envelope=setback_lines.get("sunlight_envelope"),
    )
    context = apply_registered_parcel_plan(pnu, local_site, context, parcel_policy=parcel_policy)
    floor_field = materialize_legal_floor_field(
        context, site_local_utm=local_site, pnu=pnu
    )
    shared = tuple(
        tuple(
            (point[0] - min_x, point[1] - min_y)
            for point in wgs84_to_utm(LineString(edge)).coords
        )
        for edge in (
            item.get("sharedEdge")
            for item in ((neighbors.get("neighbors") or []) if isinstance(neighbors, dict) else [])
        )
        if edge and len(edge) >= 2
    )
    return LegalSite(
        pnu=pnu,
        site_local_utm=local_site,
        site_origin_utm=(min_x, min_y),
        context=context,
        floor_field=floor_field,
        shared_edges=shared,
        building_type=building_type,
        datum=setback_lines.get("datum_result"),
        regulation=regulation,
        zone_split=zone_split_payload,
        parcel_policy=parcel_policy,
    )
