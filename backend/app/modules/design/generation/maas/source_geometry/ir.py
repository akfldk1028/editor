"""Typed source-geometry objects for ARR MAAS grammar generation."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from functools import cached_property
import hashlib
import json
from typing import Any

from shapely.geometry import Point, Polygon, box as _box, mapping
from shapely.ops import unary_union

from backend.app.modules.design.generation.maas.source_geometry.solid import AffineSurface, ConstantSurface, HeightSurface, inverse_plan_affine, mesh_mass_properties, plan_mesh, sampled_slice


# A top profile with more vertices than this is a sampled curve, not a set of
# folds, and its segment boundaries are sampling artefacts rather than creases.
#
# It lives here rather than in the renderer because it is a term of the
# `top_profile` contract below, and both sides need it: the renderer to decide
# whether to draw the seams, and a verb that folds a top to decide how many
# folds it may say. The renderer imports PIL at module level, so a verb cannot
# read the constant from there - and two copies of a number that must agree is
# how a folded plate quietly becomes a barrel vault.
MAX_CREASED_PROFILE_POINTS = 8


@dataclass(frozen=True)
class VerbTrace:
    verb: str
    params: dict[str, Any]
    status: str
    footprint_area_m2: float
    upper_area_m2: float | None = None
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "verb": self.verb,
            "params": self.params,
            "status": self.status,
            "footprint_area_m2": round(self.footprint_area_m2, 2),
        }
        if self.upper_area_m2 is not None:
            data["upper_area_m2"] = round(self.upper_area_m2, 2)
        if self.note:
            data["note"] = self.note
        return data


@dataclass(frozen=True)
class SourceVolume:
    role: str
    footprint: Polygon
    bottom_fraction: float
    top_fraction: float
    verb: str
    # A top plane that is allowed to tilt. Zero means the flat-topped prism
    # every existing consumer assumes; a positive value drops the top by that
    # share of the band's own height across the footprint, along
    # `drop_toward` (a world unit vector). This is the one term the prism
    # language lacked: without it a continuous roof - CopenHill's slope, a
    # shed, a wedge - could only be said as a staircase, and the stepping got
    # worse the finer it was cut (measured: 5 steps 0.29 articulation, 24
    # steps 0.09). Legal counting stays on the full prism, which is always
    # the stricter reading.
    top_drop: float = 0.0
    drop_toward: tuple[float, float] | None = None
    # The gable as one volume: with `ridge_along` set (world unit vector of
    # the ridge line through the plan centroid) instead of `drop_toward`, the
    # top drops on both sides of that line - two planes meeting at a ridge.
    ridge_along: tuple[float, float] | None = None
    # The general section: the top face as a piecewise-linear height profile
    # across one axis. `top_profile` is ((station, height), ...) with stations
    # ascending in [0, 1] measured along `profile_across` (world unit vector)
    # over the footprint's own extent, heights in [0, 1] of the band - 1 is
    # the band's top, 0 its bottom. A shed is two points, a gable three, a
    # mansard four, a butterfly a valley; `drop_toward` and `ridge_along` are
    # this profile's two oldest special cases and stay as written. Off-axis
    # shapes - hips, vaults - are still outside this primitive.
    top_profile: tuple[tuple[float, float], ...] | None = None
    profile_across: tuple[float, float] | None = None
    # The tilted top is walkable ground (the roof as landscape); painted as
    # ground by the renderer, otherwise the same surface.
    top_walkable: bool = False
    # The stations' AUTHORED extent along `profile_across`, as (lo, hi) world
    # scalars. Every consumer used to re-derive this range from the volume's
    # own footprint - honest for the whole volume, and a lie for any clip
    # fragment of it, which then wore the entire arc compressed across its
    # leftover width. Carried from compile so a fragment shows the SLICE of
    # the profile it actually occupies; None keeps the old footprint-derived
    # reading for anything that predates the field.
    profile_span: tuple[float, float] | None = None
    # The doubly-curved top: a bilinear surface over the footprint's extent
    # along two plan axes. `warp` is ((ux, uy), (vx, vy), (h00, h10, h11, h01),
    # plate) - world unit axes, corner heights as shares of the band (1 = the
    # band's top, at the corners (u-lo,v-lo), (u-hi,v-lo), (u-hi,v-hi),
    # (u-lo,v-hi) of the footprint's extent along u and v), and `plate` says
    # the underside follows the top (a roof plate of constant thickness)
    # rather than staying flat (a body whose top warps). The one-axis
    # `top_profile` cannot say an upswept eave whose corners rise on two
    # axes at once - the hyperbolic-paraboloid roofs a whole family of
    # competition winners rests on. Legal counting stays on the full prism.
    # An optional fifth term, `sag` (share of the band), lowers the surface
    # toward the middle of every edge and of the field - the corners keep
    # their heights, the eaves between them curve: the flying eave.
    warp: tuple | None = None

    # Explicit surfaces are shares of this volume's height band in authored
    # plan coordinates. They override legacy top/underside fields independently.
    top_surface: HeightSurface | None = None
    bottom_surface: HeightSurface | None = None
    # This domain is frozen BEFORE clipping. dataclasses.replace preserves it.
    # Legacy callers need not supply it; compile supplies the uncut plan.
    authored_domain: Polygon | None = None

    def __post_init__(self):
        if self.authored_domain is None and self.section_kind() != "flat":
            object.__setattr__(self, "authored_domain", self.footprint)

    def projection(self):
        """Declared plan region (holes retained), independent of slice height.

        Authored top/bottom pairs must define nonnegative thickness throughout
        this region. This is the conservative legal projection, not floor area.
        """
        return self.footprint

    def contains_point(self, x, y, z, low, high):
        return (self.footprint.covers(Point(x, y))
                and self.bottom_z(x, y, low, high) - 1e-9 <= z
                <= self.top_z(x, y, low, high) + 1e-9)

    @cached_property
    def surface_mesh(self):
        """Shared normalized triangles for curved slices, drawing and mass.

        Each vertex is (x, y, bottom_share, top_share). Profiles are split at
        their authored folds, so their volume integrals are exact as well.
        """
        kind = self.section_kind()
        lines = self.creases()
        triangles = plan_mesh(self.footprint, self.authored_domain or self.footprint,
                              curved=kind in ("warp", "surface"), break_lines=lines)
        return tuple(tuple((x, y, self.bottom_z(x, y, 0, 1), self.top_share(x, y))
                           for x, y in triangle) for triangle in triangles)

    def solid_volume_m3(self, low, high):
        """Material volume, never the floor-area or full-band proxy."""
        if self.section_kind() == "flat":
            return self.footprint.area * max(0.0, high-low)
        return self.mass_properties(low, high)[0]

    def mass_properties(self, low, high):
        """Uniform-density (volume, x moment, y moment, z moment)."""
        if self.section_kind() == "flat":
            mass = self.footprint.area * max(0.0, high-low)
            centre = self.footprint.centroid
            return mass, mass*centre.x, mass*centre.y, mass*(low+high)/2
        return mesh_mass_properties(self.surface_mesh, low, high)

    def transformed_plan(self, matrix):
        """Move/rotate/scale the plan and its authored surface frame together.

        ``matrix`` is a Shapely 2D affine. Out-of-plane tilts require a different
        solid representation and are deliberately not approximated by this API.
        """
        from shapely import affinity
        inverse = inverse_plan_affine(matrix)
        return replace(self, footprint=affinity.affine_transform(self.footprint, matrix),
                       authored_domain=affinity.affine_transform(self.authored_domain or self.footprint, matrix),
                       top_surface=AffineSurface(_LegacySurface(self, False), inverse),
                       bottom_surface=AffineSurface(_LegacySurface(self, True), inverse))

    # ---- The section as a height field: one owner for every consumer ----
    #
    # A volume's top is a function top(x, y) over its footprint; the flat
    # prism, the plain drop, the ridge, the one-axis profile and the warped
    # surface are five shapes of that one function. The renderer used to
    # evaluate it in one place and the gates in another, each with its own
    # branch per shape - so every new shape was five edits. Here it is once;
    # render, measure, structure and the postcondition call these.

    def section_kind(self) -> str:
        """flat | warp | profile | ridge | drop - which shape the top takes."""

        if self.top_surface is not None or self.bottom_surface is not None:
            return "surface"
        if float(self.top_drop or 0.0) <= 0.0:
            return "flat"
        if self.warp is not None:
            return "warp"
        if self.top_profile is not None and self.profile_across is not None:
            return "profile"
        if self.ridge_along is not None:
            return "ridge"
        if self.drop_toward is not None:
            return "drop"
        return "flat"

    def _unit(self, vector):
        vx, vy = vector
        norm = (vx * vx + vy * vy) ** 0.5 or 1.0
        return vx / norm, vy / norm

    @cached_property
    def _extent_cache(self) -> dict[tuple[float, float], tuple[float, float]]:
        # Instance-local derived data, just like surface_mesh. A replacement
        # or transformed volume starts fresh while retaining its authored domain.
        return {}

    def _extent_along(self, ux: float, uy: float) -> tuple[float, float]:
        key = (ux, uy)
        if key not in self._extent_cache:
            domain = self.authored_domain if self.authored_domain is not None else self.footprint
            values = [x * ux + y * uy for x, y in domain.exterior.coords]
            self._extent_cache[key] = min(values), max(values)
        return self._extent_cache[key]

    def top_share(self, x: float, y: float) -> float:
        """The top's height at a plan point as a share of the band (1 = top)."""

        if self.top_surface is not None:
            return self.top_surface.value(x, y)
        kind = self.section_kind()
        if kind == "surface":
            # Only an underside override: retain the legacy top adapter.
            return replace(self, bottom_surface=None).top_share(x, y)
        if kind == "flat":
            return 1.0
        drop = min(max(float(self.top_drop), 0.0), 1.0)
        if kind == "warp":
            (ux, uy), (vx, vy), corners, _plate = self.warp[:4]
            sag = float(self.warp[4]) if len(self.warp) > 4 else 0.0
            ux, uy = self._unit((ux, uy))
            vx, vy = self._unit((vx, vy))
            ulo, uhi = self._extent_along(ux, uy)
            vlo, vhi = self._extent_along(vx, vy)
            u = min(1.0, max(0.0, (x * ux + y * uy - ulo) / max(uhi - ulo, 1e-9)))
            v = min(1.0, max(0.0, (x * vx + y * vy - vlo) / max(vhi - vlo, 1e-9)))
            h00, h10, h11, h01 = (float(c) for c in corners)
            share = ((1 - u) * (1 - v) * h00 + u * (1 - v) * h10
                     + u * v * h11 + (1 - u) * v * h01)
            return share - sag * (4 * u * (1 - u) + 4 * v * (1 - v)) / 2.0
        if kind == "profile":
            ux, uy = self._unit(self.profile_across)
            lo_p, hi_p = self.profile_span if self.profile_span is not None else self._extent_along(ux, uy)
            u = min(1.0, max(0.0, (x * ux + y * uy - lo_p) / max(hi_p - lo_p, 1e-9)))
            return profile_height(self.top_profile, u)
        if kind == "ridge":
            rx, ry = self._unit(self.ridge_along)
            px, py = -ry, rx
            lo_p, hi_p = self._extent_along(px, py)
            centre, half = (lo_p + hi_p) / 2.0, max((hi_p - lo_p) / 2.0, 1e-9)
            t = abs(x * px + y * py - centre) / half
            return 1.0 - drop * min(1.0, t)
        ux, uy = self.drop_toward
        lo_p, hi_p = self._extent_along(ux, uy)
        t = (x * ux + y * uy - lo_p) / max(hi_p - lo_p, 1e-9)
        return 1.0 - drop * min(1.0, max(0.0, t))

    def top_z(self, x: float, y: float, low: float, high: float) -> float:
        """World height of the top at a plan point, for a band [low, high]."""

        return high - (high - low) * (1.0 - self.top_share(x, y))

    def bottom_z(self, x: float, y: float, low: float, high: float) -> float:
        """World height of the underside - flat except for a warped plate."""

        if self.bottom_surface is not None:
            return low + (high-low)*self.bottom_surface.value(x, y)
        if self.warp is not None and self.top_drop > 0 and bool(self.warp[3]):
            # A plate is a SHEET: its underside follows its top at the
            # plate's own thickness (warp[5], a share of the band), not at
            # the band's full depth. The band is thin + rise, so following at
            # the band's depth made a 1.2-storey rise a 4 m thick wedge -
            # every roof on the sheet read as a fat hat on a box, and the
            # jury said so. Missing thickness (older warps) keeps the band.
            thickness = float(self.warp[5]) if len(self.warp) > 5 else 1.0
            top = self.top_z(x, y, low, high)
            return max(low - (high - low), top - (high - low) * thickness)
        return low

    def creases(self) -> list[tuple[float, float, float]]:
        """Plan lines where the top folds: (px, py, offset) per fold.

        A ridge is one line; a profile folds at every interior station. A
        curve (a sampled arc, a warp) has no crease - drawing its samples as
        creases turned a barrel vault into corrugation.
        """

        kind = self.section_kind()
        if kind == "surface":
            return [line for surface in (self.top_surface,self.bottom_surface)
                    if surface is not None for line in surface.break_lines()]
        if kind == "ridge":
            rx, ry = self._unit(self.ridge_along)
            px, py = -ry, rx
            lo_p, hi_p = self._extent_along(px, py)
            return [(px, py, (lo_p + hi_p) / 2.0)]
        if kind == "profile":
            ux, uy = self._unit(self.profile_across)
            lo_p, hi_p = self.profile_span if self.profile_span is not None else self._extent_along(ux, uy)
            span = hi_p - lo_p
            return [(ux, uy, lo_p + u * span)
                    for u, _h in self.top_profile if 1e-6 < u < 1.0 - 1e-6]
        return []

    def plan_at(self, z: float, low: float, high: float):
        """Horizontal occupied section: bottom(x,y) <= z <= top(x,y).

        Flat prisms and legacy profiles are analytic; curved/explicit surface
        sections use the same triangulation as volume integration and rendering.
        None means no positive-area material at this level. Plan projection and
        floor-area accounting are separate queries, not implicit slice behavior.
        """
        if high <= low:
            return None
        if self.section_kind() in ("warp", "surface"):
            return sampled_slice(self.surface_mesh, z, low, high)
        if z < low - 1e-9 or z > high + 1e-9:
            return None
        return self._analytic_plan_at(z, low, high)

    def _analytic_plan_at(self, z: float, low: float, high: float):
        """Legacy analytic section for flat, drop, ridge and linear profiles.

        A band with a tilted top is solid where top(x, y) >= z and gone
        where the roof has already descended below the sample. The three
        one-axis shapes are cut analytically (exact, so the silence gate's
        area comparisons do not wobble); a warped top is sampled.
        """

        kind = self.section_kind()
        if kind == "flat":
            return self.footprint
        band = max(high - low, 1e-9)
        drop = min(max(float(self.top_drop), 0.0), 1.0)
        drop_m = drop * band
        if kind == "profile":
            rel = (z - low) / band
            points = self.top_profile
            if rel <= min(h for _u, h in points):
                return self.footprint
            ux, uy = self._unit(self.profile_across)
            lo_p, hi_p = self.profile_span if self.profile_span is not None else self._extent_along(ux, uy)
            span = max(hi_p - lo_p, 1e-9)
            kept: list[tuple[float, float]] = []
            start = points[0][0] if points[0][1] >= rel else None
            for (u0, h0), (u1, h1) in zip(points, points[1:]):
                if (h0 >= rel) != (h1 >= rel):
                    t = (rel - h0) / ((h1 - h0) or 1e-9)
                    u_cross = u0 + (u1 - u0) * t
                    if start is None:
                        start = u_cross
                    else:
                        kept.append((start, u_cross))
                        start = None
            if start is not None:
                kept.append((start, points[-1][0]))
            px, py = -uy, ux
            perp = [x * px + y * py for x, y in self.footprint.exterior.coords]
            mid_perp = (min(perp) + max(perp)) / 2.0
            reach = (max(perp) - min(perp)) + 1.0
            parts = []
            for u0, u1 in kept:
                c0 = lo_p + max(0.0, u0) * span
                c1 = lo_p + min(1.0, u1) * span
                if c1 - c0 <= 1e-9:
                    continue
                slab = Polygon([
                    (ux * c0 + px * (mid_perp - reach), uy * c0 + py * (mid_perp - reach)),
                    (ux * c1 + px * (mid_perp - reach), uy * c1 + py * (mid_perp - reach)),
                    (ux * c1 + px * (mid_perp + reach), uy * c1 + py * (mid_perp + reach)),
                    (ux * c0 + px * (mid_perp + reach), uy * c0 + py * (mid_perp + reach)),
                ])
                cut = self.footprint.intersection(slab)
                if not cut.is_empty:
                    parts.append(cut)
            return unary_union(parts) if parts else None
        if z <= high - drop_m:
            return self.footprint
        if kind == "ridge":
            rx, ry = self._unit(self.ridge_along)
            px, py = -ry, rx
            lo_p, hi_p = self._extent_along(px, py)
            centre = (lo_p + hi_p) / 2.0
            half = max((hi_p - lo_p) / 2.0, 1e-9)
            keep = half * max(0.0, (high - z) / drop_m)
            along = [x * rx + y * ry for x, y in self.footprint.exterior.coords]
            reach = (max(along) - min(along)) + 1.0
            mid_r = (max(along) + min(along)) / 2.0
            base_x = rx * mid_r + px * centre
            base_y = ry * mid_r + py * centre
            strip = Polygon([
                (base_x + rx * reach + px * keep, base_y + ry * reach + py * keep),
                (base_x - rx * reach + px * keep, base_y - ry * reach + py * keep),
                (base_x - rx * reach - px * keep, base_y - ry * reach - py * keep),
                (base_x + rx * reach - px * keep, base_y + ry * reach - py * keep),
            ])
            cut = self.footprint.intersection(strip)
            return cut if not cut.is_empty else None
        ux, uy = self.drop_toward
        lo_p, hi_p = self._extent_along(ux, uy)
        span = max(hi_p - lo_p, 1e-9)
        keep = lo_p + span * max(0.0, (high - z) / drop_m)
        reach = span + 1.0
        cx = [x for x, _y in self.footprint.exterior.coords]
        cy = [y for _x, y in self.footprint.exterior.coords]
        mid_x, mid_y = (min(cx) + max(cx)) / 2.0, (min(cy) + max(cy)) / 2.0
        base_x = mid_x + (keep - (mid_x * ux + mid_y * uy)) * ux
        base_y = mid_y + (keep - (mid_x * ux + mid_y * uy)) * uy
        px, py = -uy, ux
        half = Polygon([
            (base_x + px * reach, base_y + py * reach),
            (base_x - px * reach, base_y - py * reach),
            (base_x - px * reach - ux * reach, base_y - py * reach - uy * reach),
            (base_x + px * reach - ux * reach, base_y + py * reach - uy * reach),
        ])
        cut = self.footprint.intersection(half)
        return cut if not cut.is_empty else None

    def signature(self) -> dict[str, Any]:
        data = {
            "role": self.role,
            "verb": self.verb,
            "bottom_fraction": round(self.bottom_fraction, 3),
            "top_fraction": round(self.top_fraction, 3),
            "area_m2": round(float(self.footprint.area), 2),
            "geometry_utm": mapping(self.footprint),
            "geometry_crs": "EPSG:32652",
        }
        # Only when present, so every existing signature hash is unchanged.
        if self.top_drop > 0.0 and self.drop_toward is not None:
            data["top_drop"] = round(self.top_drop, 3)
            data["drop_toward"] = (round(self.drop_toward[0], 4), round(self.drop_toward[1], 4))
        if self.top_profile is not None:
            data["top_profile"] = [
                (round(u, 4), round(h, 4)) for u, h in self.top_profile
            ]
        if self.section_kind() != "flat":
            data["solid_query_version"] = 1
            data["top_drop"] = self.top_drop
            data["ridge_along"] = self.ridge_along
            data["profile_across"] = self.profile_across
            data["profile_span"] = self.profile_span
            data["warp"] = self.warp
            data["authored_domain"] = mapping(self.authored_domain or self.footprint)
            data["top_surface"] = self.top_surface.signature() if self.top_surface is not None else None
            data["bottom_surface"] = self.bottom_surface.signature() if self.bottom_surface is not None else None
        return data


@dataclass(frozen=True)
class _LegacySurface:
    """Typed adapter for an existing SourceVolume height field."""
    volume: SourceVolume
    underside: bool

    def value(self, x, y):
        return self.volume.bottom_z(x, y, 0, 1) if self.underside else self.volume.top_share(x, y)

    def break_lines(self):
        return tuple(self.volume.creases())

    def signature(self):
        return {"type": "legacy_adapter", "underside": self.underside,
                "volume": self.volume.signature()}


def profile_height(points: tuple[tuple[float, float], ...], u: float) -> float:
    """The profile's height at a station, linearly interpolated and clamped."""

    if u <= points[0][0]:
        return points[0][1]
    for (u0, h0), (u1, h1) in zip(points, points[1:]):
        if u <= u1:
            span = max(u1 - u0, 1e-9)
            return h0 + (h1 - h0) * (u - u0) / span
    return points[-1][1]


@dataclass(frozen=True)
class SourceSurface:
    role: str
    volume_role: str
    verb: str
    surface_type: str
    vertices_m: tuple[tuple[float, float, float], ...]
    operator: str = "extrude"
    semantic_patch_id: str = ""

    def authority_record(self) -> dict[str, Any]:
        """Serialize the exact surface fields bound by visual certificates."""

        return {
            "role": self.role,
            "volume_role": self.volume_role,
            "verb": self.verb,
            "surface_type": self.surface_type,
            "vertex_count": len(self.vertices_m),
            "vertices_m": [
                [float(x), float(y), float(z)]
                for x, y, z in self.vertices_m
            ],
            "operator": self.operator,
            "semantic_patch_id": self.semantic_patch_id,
        }

    def signature(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "volume_role": self.volume_role,
            "verb": self.verb,
            "surface_type": self.surface_type,
            "vertex_count": len(self.vertices_m),
            "vertices_m": [
                [round(x, 3), round(y, 3), round(z, 3)]
                for x, y, z in self.vertices_m
            ],
            "operator": self.operator,
            "semantic_patch_id": self.semantic_patch_id or f"{self.volume_role}:{self.surface_type}",
        }


@dataclass(frozen=True)
class SourceMass:
    name: str
    footprint: Polygon
    upper_footprint: Polygon | None = None
    lower_floor_fraction: float | None = None
    volumes: tuple[SourceVolume, ...] = ()
    surfaces: tuple[SourceSurface, ...] = ()
    verb_trace: tuple[VerbTrace, ...] = ()
    notes: tuple[str, ...] = ()
    status: str = "compiled"
    fallback_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def plan_at(self, z: float):
        """Occupied sections in metres above the mass base; ground is datum_m.

        Separate volumes can occupy several intervals on one vertical line.
        """
        height = float(self.metadata.get("authored_height_m") or 0.0)
        if height <= 0:
            return None
        parts = [v.plan_at(z, v.bottom_fraction*height, v.top_fraction*height)
                 for v in self.volumes]
        parts = [p for p in parts if p is not None and not p.is_empty]
        return unary_union(parts) if parts else None

    def contains_point(self, x: float, y: float, z: float):
        height = float(self.metadata.get("authored_height_m") or 0.0)
        return any(v.contains_point(x, y, z, v.bottom_fraction*height, v.top_fraction*height)
                   for v in self.volumes) if height > 0 else False

    def mass_properties(self, height_m=None):
        from backend.app.modules.design.generation.maas.source_geometry.solid import union_mass_properties
        height = float(height_m if height_m is not None else self.metadata.get("authored_height_m") or 0)
        return union_mass_properties(self.volumes,height) if height > 0 else (0,0,0,0)

    def solid_volume_m3(self):
        return self.mass_properties()[0]

    def body_height_m(self) -> float:
        """The tallest single body, in metres: a column of bands that share a
        plan and touch, structure left out.

        The stature gate asked for "the tallest volume's own span" and read
        one compiled band, which is not a body - the compiler cuts at every
        height where anything changes, so a gable is a storeys band plus a
        roof band and a lift is legs plus body. Read band by band, a
        four-storey house under a pitched roof delivered 5.1 m and was
        retired as crushed. Bands that share a plan and touch are one body;
        a lift's legs have their own plan and stay their own body, so empty
        clearance is still not billed as storeys.
        """

        height = float(self.metadata.get("authored_height_m") or 0.0)
        if height <= 0.0:
            return 0.0
        structural = set(self.metadata.get("structural_bands") or ())
        rooms = [volume for index, volume in enumerate(self.volumes)
                 if index not in structural]
        rooms.sort(key=lambda volume: float(volume.bottom_fraction))
        # Bands are one body when they OVERLAP in plan and touch, not when
        # their plans are identical: twist, taper, fracture and a stepped
        # grade give every storey its own outline, so an equality test read
        # a turning tower as a stack of one-storey bodies and retired it as
        # crushed. Overlap of more than half the smaller plan is one column.
        columns: list[list] = []
        for volume in rooms:
            for column in columns:
                top = column[-1]
                if float(volume.bottom_fraction) > float(top.top_fraction) + 1e-3:
                    continue
                shared = volume.footprint.intersection(top.footprint).area
                if shared > 0.5 * min(volume.footprint.area, top.footprint.area):
                    column.append(volume)
                    break
            else:
                columns.append([volume])
        # Stature is what stands up. Since `sink` the fractions are measured
        # from a base that may be below grade, and a basement shares its plan
        # with the building over it, so it joined the same column: a
        # four-storey house sunk eight metres measured twenty-two metres of
        # body and was retired as over its declared stature.
        datum = float(self.metadata.get("datum_m") or 0.0) / height
        tallest = 0.0
        for column in columns:
            low = max(datum, min(float(volume.bottom_fraction) for volume in column))
            high = max(float(volume.top_fraction) for volume in column)
            tallest = max(tallest, high - low)
        return tallest * height

    def signature(self) -> dict[str, Any]:
        areas = [float(volume.footprint.area) for volume in self.volumes]
        ground_area = float(self.footprint.area)
        upper_area = float(self.upper_footprint.area) if self.upper_footprint is not None else None
        centroid = self.footprint.centroid
        parameter_provenance = self.metadata.get("parameter_provenance", [])
        parameter_default_count = int(self.metadata.get("parameter_default_count", 0) or 0)
        parameter_authored_count = sum(
            1 for item in parameter_provenance
            if isinstance(item, dict) and not item.get("used_default")
        )
        parameter_total = parameter_default_count + parameter_authored_count
        rule_evidence = self.metadata.get("rule_evidence")
        if not isinstance(rule_evidence, dict):
            rule_evidence = {}
        rule_prior_param_count = int(rule_evidence.get("rule_prior_param_count", 0) or 0)
        llm_authored_param_count = int(rule_evidence.get("llm_authored_param_count", 0) or 0)
        rule_param_total = rule_prior_param_count + llm_authored_param_count
        primary_language = str(self.metadata.get("primary_language") or "")
        secondary_language = str(self.metadata.get("secondary_language") or "")
        reference_basis = str(self.metadata.get("reference_basis") or "")
        formal_principle = str(self.metadata.get("formal_principle") or "")
        dominant_gesture = str(self.metadata.get("dominant_gesture") or "")
        massing_genome = self.metadata.get("massing_genome")
        if not isinstance(massing_genome, dict):
            massing_genome = {}
        massing_genome_circuit = self.metadata.get("massing_genome_circuit")
        if not isinstance(massing_genome_circuit, dict):
            massing_genome_circuit = {}
        component_graph = self.metadata.get("component_graph")
        if not isinstance(component_graph, dict):
            component_graph = {}
        graph_materialization_evidence = self.metadata.get("graph_materialization_evidence")
        if not isinstance(graph_materialization_evidence, dict):
            graph_materialization_evidence = {}
        coherence_evidence = self.metadata.get("coherence_evidence")
        if not isinstance(coherence_evidence, dict):
            coherence_evidence = {}
        continuous_surface_evidence = self.metadata.get("continuous_surface_evidence")
        if not isinstance(continuous_surface_evidence, dict):
            continuous_surface_evidence = {}
        geometry_program = self.metadata.get("geometry_program")
        if not isinstance(geometry_program, dict):
            geometry_program = {}
        geometry_graph_snapshot = self.metadata.get("geometry_graph_snapshot")
        if not isinstance(geometry_graph_snapshot, dict):
            geometry_graph_snapshot = {}
        geometry_program_bridge_evidence = self.metadata.get("geometry_program_bridge_evidence")
        if not isinstance(geometry_program_bridge_evidence, dict):
            geometry_program_bridge_evidence = {}
        program_space_zones = self.metadata.get("program_space_zones")
        if not isinstance(program_space_zones, list):
            program_space_zones = []
        program_role_integration_evidence = self.metadata.get("program_role_integration_evidence")
        if not isinstance(program_role_integration_evidence, dict):
            program_role_integration_evidence = {}
        program_semantic_carrier_evidence = self.metadata.get(
            "program_semantic_carrier_evidence"
        )
        if not isinstance(program_semantic_carrier_evidence, dict):
            program_semantic_carrier_evidence = {}
        final_semantic_projection_context = self.metadata.get(
            "final_semantic_projection_context"
        )
        if not isinstance(final_semantic_projection_context, dict):
            final_semantic_projection_context = {}
        program_section_graph_evidence = self.metadata.get("program_section_graph_evidence")
        if not isinstance(program_section_graph_evidence, dict):
            program_section_graph_evidence = {}
        site_frame_evidence = self.metadata.get("site_frame_evidence")
        if not isinstance(site_frame_evidence, dict):
            site_frame_evidence = {}
        secondary_family = str(self.metadata.get("secondary_family") or "")
        if not primary_language:
            rule_descriptor = rule_evidence.get("research_diversity_descriptor")
            if isinstance(rule_descriptor, dict):
                primary_language = str(rule_descriptor.get("mass_language") or "")
        if not primary_language:
            primary_language = str(self.metadata.get("family") or "")
        if not secondary_language:
            secondary_language = str(
                massing_genome.get("vertical_strategy")
                or massing_genome.get("void_strategy")
                or massing_genome.get("connector_strategy")
                or ""
            )
        composition_layer_roles = [
            volume.role
            for volume in self.volumes
            if str(volume.role).startswith("secondary_")
        ]
        primitive_roles = {
            "polygonal": [
                volume.role
                for volume in self.volumes
                if str(volume.role).startswith("polygonal_")
            ],
            "curvilinear": [
                volume.role
                for volume in self.volumes
                if str(volume.role).startswith("curvilinear_")
            ],
            "freeform": [
                volume.role
                for volume in self.volumes
                if str(volume.role).startswith("freeform_")
            ],
        }
        principle_primitive_roles = {
            "torqued_stack": ("curvilinear_torque_axis",),
            "folded_section": ("polygonal_folded_plane",),
            "stacked_shifted_platforms": ("polygonal_shifted_platform",),
            "split_bridge_connector": ("polygonal_bridge_cut",),
            "carved_monolith": ("freeform_carved_void",),
            "carved_atrium": ("freeform_atrium_void",),
            "continuous_ribbon_field": ("curvilinear_continuous_ribbon",),
        }.get(str(formal_principle), ())
        for primitive_role in principle_primitive_roles:
            bucket = "freeform" if primitive_role.startswith("freeform_") else (
                "curvilinear" if primitive_role.startswith("curvilinear_") else "polygonal"
            )
            if primitive_role not in primitive_roles[bucket]:
                primitive_roles[bucket].append(primitive_role)
        composition_rule = ""
        if primary_language and secondary_language and secondary_language != "legal_envelope_fit":
            composition_rule = f"{primary_language}+{secondary_language}"
        ambition = self.metadata.get("architectural_ambition_evidence")
        if not isinstance(ambition, dict):
            ambition = {}
        ambition_evidence = {
            "schema_version": "arr.maas.architectural_ambition.v1",
            "reference_basis": reference_basis,
            "formal_principle": formal_principle,
            "dominant_gesture": dominant_gesture,
            "has_reference_basis": bool(reference_basis),
            "has_formal_principle": bool(formal_principle),
            "has_dominant_gesture": bool(dominant_gesture),
            **ambition,
        }
        if not ambition_evidence.get("architecture_grade_pass"):
            ambition_evidence["architecture_grade_pass"] = bool(
                ambition_evidence["has_formal_principle"]
                and ambition_evidence["has_dominant_gesture"]
                and len(composition_layer_roles) >= 1
            )
        raw_surface_count = len(self.surfaces)
        has_profiled_surfaces = any(surface.surface_type.startswith("profiled_") for surface in self.surfaces)
        logical_surface_count = len({
            surface.semantic_patch_id or f"{surface.volume_role}:{surface.surface_type}"
            for surface in self.surfaces
        })
        effective_surface_count = logical_surface_count if has_profiled_surfaces else raw_surface_count
        return {
            "schema_version": "arr.maas.source_geometry.signature.v1",
            "status": self.status,
            "family": self.metadata.get("family"),
            "primary_language": primary_language,
            "secondary_language": secondary_language,
            "reference_basis": reference_basis,
            "formal_principle": formal_principle,
            "dominant_gesture": dominant_gesture,
            "massing_genome": massing_genome,
            "massing_genome_circuit": massing_genome_circuit,
            "component_graph": component_graph,
            "graph_materialization_evidence": graph_materialization_evidence,
            "coherence_evidence": coherence_evidence,
            "continuous_surface_evidence": continuous_surface_evidence,
            "geometry_program": geometry_program,
            "geometry_graph_snapshot": geometry_graph_snapshot,
            "geometry_program_bridge_evidence": geometry_program_bridge_evidence,
            "geometry_authority": str(
                self.metadata.get("geometry_authority") or ""
            ),
            "program_space_zones": program_space_zones,
            "program_role_integration_evidence": program_role_integration_evidence,
            "program_semantic_carrier_evidence": program_semantic_carrier_evidence,
            "final_semantic_projection_context": final_semantic_projection_context,
            "actual_surface_payload_hash": _source_surface_payload_hash(
                self.surfaces
            ),
            "program_section_graph_evidence": program_section_graph_evidence,
            "site_frame_evidence": site_frame_evidence,
            "architectural_ambition_evidence": ambition_evidence,
            "secondary_family": secondary_family,
            "composition_rule": composition_rule,
            "composition_layer_roles": composition_layer_roles,
            "composition_layer_count": len(composition_layer_roles),
            "source_primitive_roles": primitive_roles,
            "source_primitive_count": sum(len(roles) for roles in primitive_roles.values()),
            "volume_count": len(self.volumes),
            "surface_count": raw_surface_count,
            "logical_surface_count": logical_surface_count,
            "effective_surface_count": effective_surface_count,
            "ground_area_m2": round(ground_area, 2),
            "upper_area_m2": round(upper_area, 2) if upper_area is not None else None,
            "upper_to_ground_ratio": round(upper_area / ground_area, 4) if upper_area and ground_area > 0 else None,
            "area_profile_m2": [round(area, 2) for area in areas],
            "verb_profile": [trace.verb for trace in self.verb_trace if trace.verb != "base"],
            "surface_roles": sorted({surface.role for surface in self.surfaces}),
            "centroid": [round(float(centroid.x), 2), round(float(centroid.y), 2)],
            "asymmetry_hint": self.metadata.get("asymmetry_hint"),
            "parameter_provenance": parameter_provenance,
            "parameter_default_count": parameter_default_count,
            "parameter_authored_count": parameter_authored_count,
            "parameter_default_ratio": round(parameter_default_count / parameter_total, 4) if parameter_total else 0.0,
            "rule_evidence": rule_evidence,
            "rule_prior_param_count": rule_prior_param_count,
            "llm_authored_param_count": llm_authored_param_count,
            "rule_prior_param_ratio": round(rule_prior_param_count / rule_param_total, 4) if rule_param_total else 0.0,
            "invalid_rule_param_count": int(rule_evidence.get("invalid_rule_param_count", 0) or 0),
        }

    def source_volume_signatures(self) -> tuple[dict[str, Any], ...]:
        return tuple(volume.signature() for volume in self.volumes)

    def source_surface_signatures(self) -> tuple[dict[str, Any], ...]:
        # Live candidate records are visual-authority payloads, not compact
        # diagnostic signatures. Preserve every hash-bearing field exactly.
        return tuple(surface.authority_record() for surface in self.surfaces)


def _source_surface_payload_hash(
    surfaces: tuple[SourceSurface, ...],
) -> str:
    records = tuple(
        json.dumps(
            {
                "operator": surface.operator,
                "role": surface.role,
                "semantic_patch_id": surface.semantic_patch_id,
                "surface_type": surface.surface_type,
                "verb": surface.verb,
                "vertices_m": [
                    [float(x), float(y), float(z)]
                    for x, y, z in surface.vertices_m
                ],
                "volume_role": surface.volume_role,
            },
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        for surface in surfaces
    )
    payload = f"[{','.join(sorted(records))}]".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
