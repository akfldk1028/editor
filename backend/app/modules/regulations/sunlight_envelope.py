"""
정북 일조사선 envelope (건축법 §61①, 시행령 §86①, 2023.9.12 개정).

**⚠️ LOCKED SPEC — DO NOT MODIFY** without reading
    `memory/arr/session14/envelope-locked-spec.md`
이 구현은 session14 (2026-04-21) 사용자 검증을 거친 결과.

================================================================
법규 §86① 단면 (북측 경계에서 남쪽으로 x 진행)
================================================================
    H (m)
    |                            /     ← slope 2:1 (H = 2x, §86①제2호)
    |                          /
    | 50 ────────────────────      ← cap (max_depth × slope)
    |                          /
    |                        /
    | 10 ────┐──────────────        ← H=10m plateau 시작 (§86①제1호)
    |        │
    |        │                     ← 수직 직각벽 (x=1.5m, H=0→10m)
    | 0 ─────┴──────────────────→ x
             1.5            25m
             ↑ base_setback

================================================================
Output 구조 (frontend renderer와 계약)
================================================================
{
  "walls": [                            # 북쪽 수직 직각벽 (§86①제1호)
    {"positions": [[lng, lat], [lng, lat]],
     "min_heights": [0.0, 0.0],         # ← datum 기준 상대값 (LOCKED)
     "max_heights": [10.0, 10.0],       # ← datum 기준 상대값 (LOCKED)
     "kind": "north_vertical"},
    ...
  ],
  "slanted_polygons": [                  # §86①제2호 경사면 (per-vertex 높이)
    {"corners": [[lng, lat, h], ...],    # h = max(10, d×2), cap 50 (datum 상대)
     "label": "...",
     "kind": "slope"},
  ],
  "profile_polylines": [...],            # 2D 단면도용 (수직→평탄→경사)
  "envelope_layers": [...],              # 계단식 시각화 (선택)
  "slope": 2.0,
  "base_setback_m": 1.5,
  "base_height_m": 10.0,
  "max_depth_m": 25.0,
  "thresholds": [...],
  "law_basis": "건축법 §61①, 시행령 §86① (2023.9.12 개정 9→10m)",
  # Phase 2A — datum metadata (선택). frontend는 datum_elevation_m이 있으면
  # walls/slanted_polygons의 height에 더해서 절대 표고 렌더 가능. 없으면 기존
  # terrain.getHeight() fallback 유지 (LOCKED SPEC).
  "datum_elevation_m": 0.0,              # §119/§86 H=0 절대 표고
  "datum_case": None,                    # "flat"|"slope_le3m"|... or None
  "datum_basis": None,                   # "ground_weighted_avg"|"road_centerline"|...
  "elevation_source": None,              # "open_meteo"|"failed"|None
                                         # None = caller가 datum 미계산 (frontend는
                                         # terrain.getHeight() fallback 사용해야 함)
}

================================================================
설계 결정 (과거 세션에서 반복 실패 후 확정)
================================================================
1. **envelope footprint = parcel.buffer(-1.5m)** (inner polygon, 42 corners)
   - 필지 외곽선에서 직접 솟으면 "떠 있는" 느낌 → 1.5m 안쪽에서 솟도록.
   - §86① "인접경계에서 1.5m 이격 내부에 건축 가능" 반영.
2. **per-vertex 높이 = max(10, d×2), cap 50m** (Ladybug solar_rights 수식)
   - d = 해당 점에서 북측 경계 MultiLineString까지 최단거리
   - 북측 edge 정의: inward normal의 -ny > 0.3 (정북 ±~72°)
3. **walls = 북쪽 edge만** (H=10m 바로 아래로 내려오는 수직벽)
   - 사용자 img_18 피드백: "직선→사선 올라가는 면은 있고,
     사선→바닥 떨어지는 수직면은 없어야 함"
   - 구현: slanted polygon corners 중 H≈10m인 인접 쌍을 wall로.
4. **남/동/서쪽 측벽 없음** (사선이 그대로 이어짐)
"""

from __future__ import annotations

import logging
import math

from pyproj import Transformer
from shapely.geometry import (
    LineString,
    MultiLineString,
    MultiPolygon,
    Point,
    Polygon,
)
from shapely.ops import transform

logger = logging.getLogger(__name__)

# ── 법규 상수 (§86①) — 수정 금지 ────────────────────────
BASE_SETBACK_M = 1.5       # §86①제1호: 인접경계 수직 이격
BASE_HEIGHT_M = 10.0       # §86①제1호: 수직벽 최대 높이 (2023.9.12 개정 9→10m)
SLOPE = 2.0                # §86①제2호: H = 2x (H/2 이격의 역수)
MAX_DEPTH_CAP_M = 25.0     # 시각화 cap: slope × max_depth = 50m (H_max)
PLATEAU_END_M = 5.0        # H=10m 평탄부 끝 (x=1.5~5m)
NORTH_EDGE_NY_THRESHOLD = 0.3  # 정북 법선 판정: -ny > 0.3 (±~72°)

_to_wgs = Transformer.from_crs("EPSG:32652", "EPSG:4326", always_xy=True)


def _utm_to_wgs(geom):
    return transform(_to_wgs.transform, geom)


def _inward_normal(edge: LineString, centroid: Point) -> tuple[float, float]:
    """edge의 내측 법선 벡터 (centroid 방향). 단위 벡터."""
    dx = edge.coords[1][0] - edge.coords[0][0]
    dy = edge.coords[1][1] - edge.coords[0][1]
    length = math.sqrt(dx * dx + dy * dy)
    if length < 0.01:
        return (0.0, 0.0)
    nx = -dy / length
    ny = dx / length
    mid = edge.interpolate(0.5, normalized=True)
    if nx * (centroid.x - mid.x) + ny * (centroid.y - mid.y) < 0:
        nx, ny = -nx, -ny
    return (nx, ny)


def _wgs_pt(utm_pt: tuple) -> list:
    p = _utm_to_wgs(Point(utm_pt[0], utm_pt[1]))
    return [p.x, p.y]


def compute_sunlight_envelope(
    north_edges: list[LineString],
    parcel_utm: Polygon,
    sunlight_rules: list | None = None,
    *,
    datum: "DatumResult | None" = None,  # type: ignore[name-defined]  # noqa: F821
) -> dict | None:
    """
    정북 일조사선 envelope 생성.

    Args:
        north_edges: _classify_edges()["north"] 리스트 (LineString, UTM)
        parcel_utm: 필지 Polygon (UTM EPSG:32652)
        sunlight_rules: 법규 rule (미사용, 호환 위해 유지)
        datum: `land.services.datum.DatumResult` 호환 객체 또는 None (keyword-only).
            제공시 envelope output에 datum_elevation_m + elevation_source 등
            metadata 추가. **walls/slanted_polygons의 height 값은 변경하지 않음**
            (LOCKED SPEC — frontend가 datum_elevation_m을 더해 절대 표고 렌더).
            None이면 elevation_source=None 으로 표시 (frontend는 terrain
            fallback 사용 신호).
            런타임 duck typing — DatumResult 외 호환 객체도 허용 (정적 타입은
            string forward ref로 명시).

    Returns:
        dict (위 모듈 docstring 구조) or None (북측 edge 없음).
    """
    try:
        if not north_edges:
            return None

        centroid = parcel_utm.centroid
        walls: list = []
        slanted_polygons: list = []
        profile_polylines: list = []
        envelope_layers: list = []
        thresholds: list = []

        # ── 1. 대표 북측 edge (혼란 방지용) ────────────────
        primary = _pick_primary_edge(north_edges, centroid)
        primary_edges = [primary[0]] if primary else []

        # ── 2. envelope slanted polygon + 북쪽 수직벽 생성 ──
        _emit_slanted_polygon_and_walls(
            north_edges, parcel_utm, centroid,
            slanted_polygons, walls, thresholds,
        )

        # ── 3a. plateau 영역 (정북 ~5m 띠) ────────────────────
        # 2026-05-11 Step 13 — frontend가 박스 윗면 전체에 노랑 plateau를 깔면
        # "사선이 plateau를 통과 안 함" 시각 오류 (사용자 docs/img_44 초록 ❌).
        # backend가 정북 boundary ~ PLATEAU_END_M 띠 polygon을 따로 계산.
        # frontend는 이 footprint로 plateau 시각화 → 그 너머는 사선만 보임.
        plateau_polygon = _emit_plateau_polygon(north_edges, parcel_utm, centroid)

        # ── 3b. 2D 단면 프로파일 (수직→평탄→경사) ───────────
        _emit_profile_polylines(primary_edges, centroid, profile_polylines)

        # ── 4. 계단식 envelope 층 (선택적 시각화) ──────────
        _emit_envelope_layers(north_edges, parcel_utm, centroid, envelope_layers)

        if not walls and not slanted_polygons and not envelope_layers:
            return None

        # ── 5. datum metadata (Phase 2A, optional) ─────────
        # walls/slanted_polygons height는 datum 기준 **상대값** 유지 (LOCKED SPEC).
        # frontend가 datum_elevation_m을 entity height에 더해 절대 표고 렌더.
        datum_meta = _extract_datum_meta(datum)

        return {
            "walls": walls,
            "slanted_polygons": slanted_polygons,
            "plateau_polygon": plateau_polygon,
            "profile_polylines": profile_polylines,
            "envelope_layers": envelope_layers,
            "slope": SLOPE,
            "base_setback_m": BASE_SETBACK_M,
            "base_height_m": BASE_HEIGHT_M,
            "max_depth_m": MAX_DEPTH_CAP_M,
            "plateau_end_m": PLATEAU_END_M,
            "thresholds": thresholds,
            "law_basis": "건축법 §61①, 시행령 §86① (2023.9.12 개정 9→10m)",
            **datum_meta,
        }

    except Exception as e:
        logger.warning(f"sunlight_envelope failed: {e}")
        return None


_DEFAULT_DATUM_META: dict = {
    "datum_elevation_m": 0.0,
    "datum_case": None,
    "datum_basis": None,
    "elevation_source": None,   # None = caller가 datum 미계산
}


def _extract_datum_meta(datum: "DatumResult | None") -> dict:  # type: ignore[name-defined]  # noqa: F821
    """
    DatumResult → envelope output metadata.

    None / 무효 입력시 안전한 default (LOCKED SPEC: datum=0이면 기존 동작).

    Duck-typed 입력: hasattr(datum, "elevation_m"/"case"/"basis"/"elevation_source")
    이 형태면 land.services.datum.DatumResult 또는 호환 객체로 간주.
    str/dict/int 등 비호환 입력 → defaults (안전).
    """
    if datum is None:
        return dict(_DEFAULT_DATUM_META)

    # 비호환 객체 (str, dict, int 등) → defaults
    if not hasattr(datum, "elevation_m"):
        return dict(_DEFAULT_DATUM_META)

    elev_raw = getattr(datum, "elevation_m", None)
    try:
        elev = float(elev_raw) if elev_raw is not None else 0.0
    except (TypeError, ValueError):
        elev = 0.0

    case = getattr(datum, "case", None)
    case_str = case.value if hasattr(case, "value") else (str(case) if case else None)
    basis = getattr(datum, "basis", None)
    src = getattr(datum, "elevation_source", None)
    return {
        "datum_elevation_m": elev,
        "datum_case": case_str,
        "datum_basis": basis if basis else None,
        "elevation_source": src if src else None,
    }


# ───────────────────────────────────────────────────────────────
# Internal helpers
# ───────────────────────────────────────────────────────────────


def _pick_primary_edge(edges: list[LineString], centroid: Point) -> tuple | None:
    """북측 edge 중 '가장 대표적인' edge 1개 선택. 기준: length × max(0, -ny)."""
    best = None
    best_score = -1.0
    for e in edges:
        nx_, ny_ = _inward_normal(e, centroid)
        if nx_ == 0 and ny_ == 0:
            continue
        sc = e.length * max(0.0, -ny_)
        if sc > best_score:
            best_score = sc
            best = (e, nx_, ny_)
    return best


def _emit_slanted_polygon_and_walls(
    north_edges: list[LineString],
    parcel_utm: Polygon,
    centroid: Point,
    slanted_polygons: list,
    walls: list,
    thresholds: list,
) -> None:
    """
    핵심 로직. 북측 경계로부터 per-vertex distance 기반 envelope 생성.

    - envelope footprint = parcel.buffer(-1.5m) 의 외곽 ring
    - 각 vertex: d = 북쪽 MultiLineString 최단거리
    - H = min(50, max(10, d × 2))
    - walls: H ≈ 10m 인접 쌍 → 북쪽 수직벽 (H=0→10m)
    """
    try:
        # 정북 edge 필터 (inward -ny > 0.3 = 정북 ±~72°)
        north_lines = [
            e for e in north_edges
            if -_inward_normal(e, centroid)[1] > NORTH_EDGE_NY_THRESHOLD
        ]
        if not north_lines:
            north_lines = list(north_edges)

        if not north_lines:
            return

        north_mls = (
            MultiLineString(north_lines) if len(north_lines) > 1 else north_lines[0]
        )

        # envelope 바닥 outline: parcel을 1.5m 안쪽으로 이격
        try:
            inner_poly = parcel_utm.buffer(-BASE_SETBACK_M)
            if isinstance(inner_poly, MultiPolygon):
                inner_poly = max(inner_poly.geoms, key=lambda g: g.area)
            if not isinstance(inner_poly, Polygon) or inner_poly.area < 1.0:
                inner_poly = parcel_utm
        except Exception:
            inner_poly = parcel_utm

        # 2026-05-11 Step 11 — ring densify (사용자 docs/img_41,42 요구).
        # corner만 sample하면 plateau(d<5, H=10 평탄 영역)가 정북 edge 1차원 line에만 존재 →
        # 사선 polygon이 정북 corner에서 바로 위로 솟아 "수평 plateau 없이 곧장 사선"으로 보임.
        # inner_poly.segmentize(1.0)로 1m 간격 dense vertex 추가 → d=5 contour 통과 vertex 생성 →
        # perPositionHeight polygon이 d=0~5 평탄(H=10) + d>5 사선 정확히 표현.
        try:
            inner_poly_dense = inner_poly.segmentize(1.0)
            ring_utm = list(inner_poly_dense.exterior.coords)[:-1]
        except Exception:
            ring_utm = list(inner_poly.exterior.coords)[:-1]
        # 2026-05-11 Step 12 — primary edge perpendicular distance (대칭 강제).
        # 사용자 docs/img_42 좌우 비대칭 지적: parcel이 약간 비스듬하면 north_mls.distance
        # (각 정북 edge segment까지 최단거리)가 좌우 corner에 다른 값 반환 → 한쪽 plateau ✅
        # 다른쪽 사선 ❌. primary 정북 edge의 line(양방향 무한 확장)으로부터의 수직거리만
        # 사용하면 같은 axis에 수직인 vertex는 같은 d → 좌우 대칭 plateau-사선 transition.
        primary_full = _pick_primary_edge(north_lines, centroid)
        if primary_full:
            pe = primary_full[0]
            pe_coords = list(pe.coords)
            pe_p1 = pe_coords[0]
            pe_p2 = pe_coords[-1]
            pe_dx = pe_p2[0] - pe_p1[0]
            pe_dy = pe_p2[1] - pe_p1[1]
            pe_len = math.sqrt(pe_dx * pe_dx + pe_dy * pe_dy)
        else:
            pe_len = 0.0
            pe_p1 = pe_p2 = None
            pe_dx = pe_dy = 0.0

        def _d_perp(pt: tuple) -> float:
            """primary edge line으로부터의 perpendicular distance (대칭). fallback: north_mls."""
            if pe_len > 0.01 and pe_p1 is not None:
                # |dy*(x-x1) - dx*(y-y1)| / len
                return abs(pe_dy * (pt[0] - pe_p1[0]) - pe_dx * (pt[1] - pe_p1[1])) / pe_len
            return north_mls.distance(Point(pt[0], pt[1]))

        corners_utm_h: list[list] = []
        for pt in ring_utm:
            d = _d_perp(pt)
            h = min(SLOPE * MAX_DEPTH_CAP_M, max(BASE_HEIGHT_M, d * SLOPE))
            corners_utm_h.append([pt[0], pt[1], h])

        corners_wgs = [[*_wgs_pt((c[0], c[1])), c[2]] for c in corners_utm_h]
        slanted_polygons.append({
            "corners": corners_wgs,
            "label": "정북일조 envelope (§86① H = max(10, d×2), 1.5m 이격 내부)",
            "kind": "slope",
        })

        min_h = min(c[2] for c in corners_utm_h)
        max_h = max(c[2] for c in corners_utm_h)
        thresholds.append({"distance_m": 0.0, "max_height_m": min_h, "kind": "vertical"})
        thresholds.append({"distance_m": MAX_DEPTH_CAP_M, "max_height_m": max_h,
                           "kind": "slope_top"})

        # 북쪽 수직벽: H≈10m 인접 쌍 → 바닥까지 내려오는 수직벽
        # (사용자 img_18: "직선→사선 올라가는 면" 유지)
        n = len(corners_utm_h)
        for i in range(n):
            c1 = corners_utm_h[i]
            c2 = corners_utm_h[(i + 1) % n]
            if (abs(c1[2] - BASE_HEIGHT_M) < 0.5
                    and abs(c2[2] - BASE_HEIGHT_M) < 0.5):
                walls.append({
                    "positions": [_wgs_pt((c1[0], c1[1])), _wgs_pt((c2[0], c2[1]))],
                    "min_heights": [0.0, 0.0],
                    "max_heights": [BASE_HEIGHT_M, BASE_HEIGHT_M],
                    "kind": "north_vertical",
                })
    except Exception as e:
        logger.warning(f"envelope from north boundary failed: {e}")


def _emit_plateau_polygon(
    north_edges: list[LineString],
    parcel_utm: Polygon,
    centroid: Point,
) -> dict | None:
    """
    정북 boundary ~ PLATEAU_END_M 띠 polygon (H=10m 평탄부, §86①제1호).

    사용자 docs/img_44 요구: plateau가 박스 윗면 전체가 아니라 정북 5m 부분만이어야.
    inner_poly (parcel - 1.5m buffer) ∩ (primary edge inward 5m strip).

    Returns dict {"corners": [[lng, lat, 10]...], "kind": "plateau"} or None.
    """
    try:
        if not north_edges:
            return None
        primary = _pick_primary_edge(north_edges, centroid)
        if not primary:
            return None
        edge, nx, ny = primary
        coords = list(edge.coords)
        a, b = coords[0], coords[-1]
        edge_dx = b[0] - a[0]
        edge_dy = b[1] - a[1]
        edge_len = math.sqrt(edge_dx * edge_dx + edge_dy * edge_dy)
        if edge_len < 0.01:
            return None

        # primary edge를 양옆 100m 확장 → inner_poly 완전 cross
        ext = 100.0 / edge_len
        ax = a[0] - edge_dx * ext
        ay = a[1] - edge_dy * ext
        bx = b[0] + edge_dx * ext
        by = b[1] + edge_dy * ext

        # primary edge에서 inward로 PLATEAU_END_M 영역 strip
        strip_coords = [
            (ax, ay),
            (bx, by),
            (bx + nx * PLATEAU_END_M, by + ny * PLATEAU_END_M),
            (ax + nx * PLATEAU_END_M, ay + ny * PLATEAU_END_M),
        ]
        strip = Polygon(strip_coords)
        if not strip.is_valid:
            strip = strip.buffer(0)

        # inner_poly (parcel - 1.5m) 와 교집합 → 정북 1.5m~5m 띠
        try:
            inner_poly = parcel_utm.buffer(-BASE_SETBACK_M)
            if isinstance(inner_poly, MultiPolygon):
                inner_poly = max(inner_poly.geoms, key=lambda g: g.area)
            if not isinstance(inner_poly, Polygon) or inner_poly.area < 1.0:
                inner_poly = parcel_utm
        except Exception:
            inner_poly = parcel_utm

        plateau = inner_poly.intersection(strip)
        if plateau.is_empty:
            return None
        if isinstance(plateau, MultiPolygon):
            plateau = max(plateau.geoms, key=lambda g: g.area)
        if not isinstance(plateau, Polygon) or plateau.area < 0.5:
            return None

        ring_wgs = [_wgs_pt(p) for p in list(plateau.exterior.coords)[:-1]]
        return {
            "corners": [[p[0], p[1], BASE_HEIGHT_M] for p in ring_wgs],
            "label": f"정북 {PLATEAU_END_M:.0f}m 평탄부 (§86①제1호 H=10m)",
            "kind": "plateau",
        }
    except Exception as e:
        logger.warning(f"plateau polygon failed: {e}")
        return None


def _emit_profile_polylines(
    primary_edges: list[LineString],
    centroid: Point,
    profile_polylines: list,
) -> None:
    """2D 단면도용 프로파일 (수직→평탄→경사)."""
    for edge in primary_edges:
        nx, ny = _inward_normal(edge, centroid)
        if nx == 0.0 and ny == 0.0:
            continue
        if len(edge.coords) < 2:
            continue
        mid = edge.interpolate(0.5, normalized=True)
        mid_xy = (mid.x, mid.y)

        pts_utm_h = [
            (mid_xy[0] + nx * BASE_SETBACK_M, mid_xy[1] + ny * BASE_SETBACK_M, 0.0),
            (mid_xy[0] + nx * BASE_SETBACK_M, mid_xy[1] + ny * BASE_SETBACK_M, BASE_HEIGHT_M),
        ]
        if PLATEAU_END_M > BASE_SETBACK_M:
            pts_utm_h.append(
                (mid_xy[0] + nx * PLATEAU_END_M, mid_xy[1] + ny * PLATEAU_END_M, BASE_HEIGHT_M)
            )
        if MAX_DEPTH_CAP_M > PLATEAU_END_M:
            pts_utm_h.append(
                (mid_xy[0] + nx * MAX_DEPTH_CAP_M, mid_xy[1] + ny * MAX_DEPTH_CAP_M,
                 SLOPE * MAX_DEPTH_CAP_M)
            )
        pts_wgs_h = [[*_wgs_pt((p[0], p[1])), p[2]] for p in pts_utm_h]
        profile_polylines.append({
            "points": pts_wgs_h,
            "label": "단면 프로파일 (수직→평탄→경사)",
        })


def _emit_envelope_layers(
    north_edges: list[LineString],
    parcel_utm: Polygon,
    centroid: Point,
    envelope_layers: list,
) -> None:
    """적응형 계단식 envelope 층 (필지 크기에 따라 자동)."""
    candidate_heights = [10.0, 15.0, 20.0, 25.0, 30.0]
    kind_names = ["base", "mid", "high", "high2", "top"]
    h_bot = 0.0
    for i, h_top in enumerate(candidate_heights):
        if h_top > SLOPE * MAX_DEPTH_CAP_M + 0.01:
            break
        offset_req = max(BASE_SETBACK_M, h_top * 0.5)
        fp = _offset_north_edges_footprint(north_edges, parcel_utm, centroid, offset_req)
        if fp is None:
            break
        kind = kind_names[i] if i < len(kind_names) else "top"
        ring_wgs = [_wgs_pt(p) for p in fp.exterior.coords[:-1]]
        envelope_layers.append({
            "footprint_wgs": ring_wgs,
            "h_bottom": h_bot,
            "h_top": h_top,
            "offset_m": offset_req,
            "kind": kind,
            "label": f"H={h_bot:.0f}~{h_top:.0f}m (offset≥{offset_req:.1f}m)",
        })
        h_bot = h_top


def _offset_north_edges_footprint(
    north_edges: list[LineString],
    parcel_utm: Polygon,
    centroid: Point,
    offset_m: float,
) -> Polygon | None:
    """H 이하 층에서 건축 가능한 footprint (north half-plane ∩ parcel)."""
    if not north_edges:
        return None
    best_edge = None
    best_score = -1.0
    for edge in north_edges:
        nx, ny = _inward_normal(edge, centroid)
        if nx == 0.0 and ny == 0.0:
            continue
        score = edge.length * max(0.0, -ny)
        if score > best_score:
            best_score = score
            best_edge = (edge, nx, ny)
    if not best_edge:
        return None
    edge, nx, ny = best_edge
    coords_u = list(edge.coords)
    a, b = coords_u[0], coords_u[-1]
    big = 200.0
    hp_coords = [
        (a[0] + nx * offset_m, a[1] + ny * offset_m),
        (b[0] + nx * offset_m, b[1] + ny * offset_m),
        (b[0] + nx * big, b[1] + ny * big),
        (a[0] + nx * big, a[1] + ny * big),
    ]
    try:
        half = Polygon(hp_coords)
        if not half.is_valid:
            half = half.buffer(0)
        result = parcel_utm.intersection(half)
    except Exception:
        return None
    if result.is_empty:
        return None
    if isinstance(result, MultiPolygon):
        result = max(result.geoms, key=lambda g: g.area)
    if not isinstance(result, Polygon) or result.area < 1.0:
        return None
    return result
