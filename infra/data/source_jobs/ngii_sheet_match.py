"""Match spatial sheet identity independently of catalogue publication dates."""
import math
import re
from pathlib import PurePosixPath

def select_sheet(rows, sheet, file_year):
    candidates = [r for r in rows if r.get('sheet') == sheet and r.get('projection') == 'GRS80' and int(r.get('scale') or 999999) <= 5000]
    if not candidates:
        return None
    signatures = []
    for row in candidates:
        bounds = tuple(float(row[k]) for k in ('minx', 'miny', 'maxx', 'maxy'))
        if not all(math.isfinite(v) for v in bounds) or bounds[0] >= bounds[2] or bounds[1] >= bounds[3]:
            raise ValueError('Invalid sheet bounds')
        signatures.append((int(row['scale']), bounds))
    scale, reference = signatures[0]
    if any(s != scale or any(abs(a-b)>1e-6 for a,b in zip(bounds,reference)) for s,bounds in signatures):
        raise ValueError('Conflicting sheet bounds or scale')
    return next((r for r in candidates if str(r.get('year', '')).startswith(file_year)), candidates[0])

def elevation_kind(member):
    name = PurePosixPath(member.replace('\\', '/')).name
    if re.fullmatch(r'N[123]L_F0010000\.shp', name, re.IGNORECASE):
        return 'contour'
    if re.fullmatch(r'N[123]P_F0020000\.shp', name, re.IGNORECASE):
        return 'spot'
    return None
