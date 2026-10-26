"""NGII 1:5000 Map Index Resolver & Site Context Extractor for 25_ACE.

Given a coordinate (lat, lon) or bounding box:
1. Identifies which NGII 1:5000 sheet(s) cover the area.
2. Extracts surrounding buildings (with storeys/height), roads, and elevations.
3. Exports clean, lightweight GeoJSON for MasterPlanAgent and other agents.
"""
from __future__ import annotations
import source_job_paths as sjp

import glob
import json
import os
import math
import sys
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import pyogrio
from pyproj import Transformer
from shapely.geometry import Point, box, mapping


DATA_ROOT = sjp.SOURCE_DATA_ROOT
RAW_NGII = DATA_ROOT / "raw" / "ngii_map"
PROCESSED_ROOT = sjp.DATA_ROOT / "processed"
INDEX_FILE = sjp.INDEX_STATE_ROOT / "registry.json"


# Two NGII products share the layer codes but not the column names:
#   B010 수치지형도 v2.0 도엽별 (cp949, Korean columns: 도로폭·차로수·층수 ...)
#   B020 연속수치지형도 사용자정의영역 (UTF-8, 4-letter codes: rvwd 도로폭, rdln 차로수, nmly 층수, nume 표고 ...)
B020_COLUMNS = {
    "buildings": {"nmly": "storeys", "name": "name", "kind": "kind", "serv": "service", "bjcd": "bjd_code", "ufid": "ufid"},
    "roads": {"rvwd": "도로폭", "rdln": "차로수", "onsd": "일방통행", "rdnm": "도로명코드", "rdnu": "도로번호", "rddv": "도로구분",
              "pvqt": "포장", "name": "명칭", "ufid": "UFID"},
    "elevations": {"nume": "elevation", "ufid": "ufid"},
}
ONE_WAY_CODES = {"ITH001": "일방통행", "ITH002": "양방통행"}


def sheet_encoding(folder: Path) -> str:
    """The .cpg beside the shapefiles decides (B020 ships UTF-8); B010 sheets are cp949."""
    for cpg in folder.glob("*.cpg"):
        try:
            text = cpg.read_text(encoding="ascii", errors="ignore").strip().upper()
        except OSError:
            continue
        if "UTF" in text:
            return "utf-8"
        if text:
            return "cp949"
    return "cp949"


def sheet_product(folder: Path) -> str:
    name = folder.name
    return "B020" if name.startswith("(B020)") else "B010" if name.startswith("(B010)") else "unknown"


def read_layer(folder: Path, layer: str, kind: str | None = None, *, bbox=None):
    """A layer of one sheet folder in WGS84 with B020 columns renamed to the B010 names downstream expects."""
    if (folder / '.sitecontext-install-incomplete.json').exists():
        raise ValueError('NGII source installation is incomplete')
    paths = sorted(set(folder.glob(f'{layer}.shp')) | set(folder.glob(f'{layer}_*.shp')))
    if not paths:
        return None
    frames = []
    for path in paths:
        info = pyogrio.read_info(path)
        query = None
        if bbox is not None:
            query = Transformer.from_crs(4326, info['crs'], always_xy=True).transform_bounds(*bbox)
            a, b, c, d = info['total_bounds']
            if query[2] < a or query[0] > c or query[3] < b or query[1] > d:
                continue
        frame = gpd.read_file(path, engine='pyogrio', bbox=query,
                              encoding=sheet_encoding(folder)).to_crs('EPSG:4326')
        if bbox is not None:
            frame = frame.cx[bbox[0]:bbox[2], bbox[1]:bbox[3]]
        frames.append(frame)
    if not frames:
        return None
    gdf = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs='EPSG:4326')
    if sheet_product(folder) == "B020" and kind in B020_COLUMNS:
        gdf = gdf.rename(columns={k: B020_COLUMNS[kind][k.lower()] for k in gdf.columns
                                  if k.lower() in B020_COLUMNS[kind]})
        if "일방통행" in gdf.columns:
            gdf["일방통행"] = gdf["일방통행"].map(lambda v: ONE_WAY_CODES.get(v, v))
    return gdf


def scan_sheets() -> list[dict[str, Any]]:
    """Scan raw/ngii_map and return metadata and bounds for all downloaded sheets (B010 도엽 or B020 영역)."""
    sheets = []
    folders = sorted({p.parent for p in RAW_NGII.rglob('N3*.shp')})
    for folder in folders:
        if (folder / '.sitecontext-install-incomplete.json').exists():
            continue
        p = folder / 'N3A_B0010000.shp'
        folder_name = p.parent.name
        sheet_id = ""
        for part in folder_name.split("_"):
            if len(part) == 8 and part.isdigit():
                sheet_id = part
                break
        if not sheet_id:
            sheet_id = folder_name  # B020 user-defined areas carry no sheet number; bounds come from the data
        try:
            layers = []
            for layer_path in sorted(folder.glob('N3*.shp')):
                info = pyogrio.read_info(layer_path)
                bounds = Transformer.from_crs(info['crs'], 4326, always_xy=True).transform_bounds(*info['total_bounds'])
                if not all(math.isfinite(v) for v in bounds):
                    continue
                layers.append({'file': layer_path.name, 'bounds_wgs84': list(bounds), 'features': int(info['features'])})
            if not layers:
                continue
            minx = min(x['bounds_wgs84'][0] for x in layers)
            miny = min(x['bounds_wgs84'][1] for x in layers)
            maxx = max(x['bounds_wgs84'][2] for x in layers)
            maxy = max(x['bounds_wgs84'][3] for x in layers)
            sheets.append({
                "sheet_id": sheet_id,
                "product": sheet_product(p.parent),
                "encoding": sheet_encoding(p.parent),
                "folder": str(p.parent.relative_to(DATA_ROOT)).replace("\\", "/"),
                "bounds_wgs84": [round(minx, 5), round(miny, 5), round(maxx, 5), round(maxy, 5)],
                "building_count": sum(x['features'] for x in layers if x['file'].startswith('N3A_B0010000')),
                "layers": layers,
            })
        except Exception as exc:
            sheets.append({
                "sheet_id": sheet_id,
                "folder": str(p.parent.relative_to(DATA_ROOT)).replace("\\", "/"),
                "error": str(exc),
            })
    return sheets


def build_index_registry() -> dict[str, Any]:
    """Build and save index/registry.json cataloging all raw and processed data."""
    sheets = scan_sheets()
    registry = {
        "__description": "25_ACE Nationwide Spatial Context & GIS Registry",
        "sheets": sheets,
        "processed_contexts": [
            {
                "id": "seoul_gangnam",
                "center": [127.036, 37.500],
                "description": "Yeoksam-dong 677 & Teheran-ro corridor",
                "buildings": "processed/seoul/gangnam/buildings.geojson",
                "roads": "processed/seoul/gangnam/roads.geojson",
                "elevations": "processed/seoul/gangnam/elevations.geojson",
            }
        ]
    }
    INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    if INDEX_FILE.exists():
        previous = json.loads(INDEX_FILE.read_text(encoding='utf-8'))
        registry['processed_contexts'] = previous.get('processed_contexts', registry['processed_contexts'])
    temporary = INDEX_FILE.with_suffix('.tmp')
    temporary.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(INDEX_FILE)
    return registry


def find_sheets_for_bbox(minx: float, miny: float, maxx: float, maxy: float) -> list[Path]:
    """Find all downloaded sheet folders that intersect the given bbox."""
    if not INDEX_FILE.exists():
        build_index_registry()
    reg = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    matched = []
    for s in reg.get("sheets", []):
        if "bounds_wgs84" in s:
            s_minx, s_miny, s_maxx, s_maxy = s["bounds_wgs84"]
            # Check overlap
            if not (maxx < s_minx or minx > s_maxx or maxy < s_miny or miny > s_maxy):
                matched.append(DATA_ROOT / s["folder"])
    return matched


def extract_context(lon: float, lat: float, radius_deg: float = 0.005,
                    out_dir: Path | None = None) -> dict[str, Any]:
    """Extract buildings, roads, and elevations around a point into GeoJSON."""
    minx, miny = lon - radius_deg, lat - radius_deg
    maxx, maxy = lon + radius_deg, lat + radius_deg

    sheets = find_sheets_for_bbox(minx, miny, maxx, maxy)
    if not sheets:
        raise FileNotFoundError(f"No downloaded NGII sheet covers ({lon}, {lat}) within radius.")


    # 1. Buildings
    bldg_frames = []
    cols_map = {'명칭': 'name', '구분': 'division', '종류': 'kind', '용도': 'use',
                '주기': 'label', '층수': 'storeys', 'UFID': 'ufid'}
    for s in sheets:
        gdf = read_layer(s, "N3A_B0010000", "buildings", bbox=(minx, miny, maxx, maxy))
        if gdf is not None:
            gdf = gdf.rename(columns={k: v for k, v in cols_map.items() if k in gdf.columns})
            keep = [c for c in ['name', 'use', 'kind', 'storeys', 'ufid', 'geometry'] if c in gdf.columns]
            clipped = gdf[keep].cx[minx:maxx, miny:maxy]
            if not clipped.empty:
                bldg_frames.append(clipped)
    bldg_clip = pd.concat(bldg_frames, ignore_index=True) if bldg_frames else gpd.GeoDataFrame()

    # 2. Roads
    road_frames = []
    for s in sheets:
        gdf = read_layer(s, "N3L_A0020000", "roads", bbox=(minx, miny, maxx, maxy))
        if gdf is not None:
            clipped = gdf.cx[minx:maxx, miny:maxy]
            if not clipped.empty:
                road_frames.append(clipped)
    road_clip = pd.concat(road_frames, ignore_index=True) if road_frames else None

    # 3. Elevations
    elev_frames = []
    for s in sheets:
        gdf = read_layer(s, "N3P_F0020000", "elevations", bbox=(minx, miny, maxx, maxy))
        if gdf is not None:
            clipped = gdf.cx[minx:maxx, miny:maxy]
            if not clipped.empty:
                elev_frames.append(clipped)
    elev_clip = pd.concat(elev_frames, ignore_index=True) if elev_frames else None

    area_frames = []
    for s in sheets:
        gdf = read_layer(s, "N3A_A0010000", bbox=(minx, miny, maxx, maxy))
        if gdf is not None:
            clipped = gdf.cx[minx:maxx, miny:maxy]
            if not clipped.empty:
                area_frames.append(clipped)
    area_clip = pd.concat(area_frames, ignore_index=True) if area_frames else None

    out_paths = {}
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        if area_clip is not None and not area_clip.empty:
            area_out = out_dir / "road_areas.geojson"
            area_clip.to_file(area_out, driver="GeoJSON")
            out_paths["road_areas"] = str(area_out)
        bldg_out = out_dir / "buildings.geojson"
        if not bldg_clip.empty:
            bldg_clip.to_file(bldg_out, driver="GeoJSON")
            out_paths["buildings"] = str(bldg_out)

        if road_clip is not None and not road_clip.empty:
            road_out = out_dir / "roads.geojson"
            road_clip.to_file(road_out, driver="GeoJSON")
            out_paths["roads"] = str(road_out)

        if elev_clip is not None and not elev_clip.empty:
            elev_out = out_dir / "elevations.geojson"
            elev_clip.to_file(elev_out, driver="GeoJSON")
            out_paths["elevations"] = str(elev_out)

    return {
        "status": "extracted",
        "sheets": [str(s) for s in sheets],
        "center": [lon, lat],
        "counts": {
            "buildings": len(bldg_clip),
            "roads": len(road_clip) if road_clip is not None else 0,
            "elevations": len(elev_clip) if elev_clip is not None else 0,
        },
        "files": out_paths,
    }


if __name__ == "__main__":
    print("Building NGII Index Registry...")
    reg = build_index_registry()
    print(f"Indexed {len(reg['sheets'])} sheets.")
    print("Extracting Yeoksam 677 context to processed/seoul/gangnam...")
    res = extract_context(127.036, 37.500, radius_deg=0.005,
                          out_dir=PROCESSED_ROOT / "seoul" / "gangnam")
    print("Result:", json.dumps(res, indent=2, ensure_ascii=False))
