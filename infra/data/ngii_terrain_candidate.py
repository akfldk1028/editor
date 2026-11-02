"""Prepare official B021 terrain candidates, never modify the active map release.

Input records remain in EPSG:5179; candidate lattice uses EPSG:5186/5 m to
align the already verified original-sheet refinement rasters.
"""
import argparse
import hashlib
import json
import math
import os
import re
from pathlib import Path
import shutil

RECIPE = 'ngii-b021-cont-spot-tin-5m-radius1000-v1'
LAYERS = {'N3L_F0010000': 'CONT', 'N3P_F0020000': 'NUME'}
GIB = 1024 ** 3


def elevation_layer(member):
    name = Path(member.replace('\\', '/')).stem
    return next((layer for layer in LAYERS if re.fullmatch(re.escape(layer) + r'(?:_\d+)?', name)), None)


def packed(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def reserve(path, extra=0, reserve_bytes=20 * GIB):
    path = Path(path)
    while not path.exists():
        path = path.parent
    if shutil.disk_usage(path).free - extra < reserve_bytes:
        raise RuntimeError('Terrain candidate would breach the 20 GiB storage reserve')


def plan_sources(root):
    root = Path(root).resolve()
    national = root / 'national-continuous-source-inventory.json'
    metadata = json.loads(national.read_text(encoding='utf8'))
    if (metadata.get('productCode'), metadata.get('scale'), metadata.get('year'), metadata.get('format')) != ('B021', 5000, 2024, 'SHP'):
        raise ValueError('Unexpected official continuous source snapshot')
    sources = {}
    for code, area in sorted(metadata['providerAreas'].items()):
        inventory = root / area['inventoryFile']
        for row in json.loads(inventory.read_text(encoding='utf8')):
            layer = elevation_layer(row['shp'])
            if layer is None:
                continue
            if row['crs'] != 'EPSG:5179' or not {'UFID', LAYERS[layer]} <= set(row['fields']):
                raise ValueError('Unverified elevation schema')
            archive = root / row.get('path', f'{code}-files/{row["zip"]}')
            disks = sorted(archive.parent.glob(archive.stem + '.z[0-9][0-9]')) + [archive]
            bindings = []
            for disk in disks:
                receipt_path = disk.with_suffix(disk.suffix + '.receipt.json')
                receipt = json.loads(receipt_path.read_text(encoding='utf8'))
                if receipt.get('provider') != 'NGII' or receipt.get('format') != 'SHP' or receipt.get('requestedYear', receipt.get('year')) != 2024 or receipt.get('requestedScale', receipt.get('scale')) != 5000:
                    raise ValueError('Unexpected elevation source receipt')
                stat = disk.stat()
                if stat.st_size != receipt['bytes']:
                    raise ValueError('Elevation source size differs from verified receipt')
                bindings.append({'path': str(disk), 'bytes': stat.st_size, 'mtimeNs': stat.st_mtime_ns,
                                 'sha256': receipt['sha256'], 'receiptSHA256': sha(receipt_path.read_bytes())})
            identity = sha(packed([[b['sha256'] for b in bindings], row['shp']]))
            alias = {'providerArea': code, 'variant': row.get('variant'), 'inventorySHA256': sha(inventory.read_bytes())}
            if identity in sources:
                sources[identity]['aliases'].append(alias)
            else:
                sources[identity] = {'id': identity, 'layer': layer, 'field': LAYERS[layer], 'shp': row['shp'],
                    'expectedRows': row['features'], 'bounds5179': row['bounds'], 'bindings': bindings, 'aliases': [alias]}
    covered = {}
    for source in sources.values():
        for alias in source['aliases']:
            covered.setdefault((alias['providerArea'], alias['variant']), set()).add(source['layer'])
    if set(code for code, _ in covered) != set(metadata['providerAreas']) or any(layers != set(LAYERS) for layers in covered.values()):
        raise ValueError('An official provider area/variant is missing contour or spot layers')
    return {'nationalInventorySHA256': sha(national.read_bytes()), 'providerAreaCount': len(metadata['providerAreas']),
            'sources': list(sources.values()), 'expectedRows': sum(s['expectedRows'] for s in sources.values())}


def elevation_points(properties, geometry, layer, transform, native_bounds=None):
    """All original line/point vertices; zero remains valid. Invalid data is audited, not invented."""
    import numpy as np
    from shapely import get_coordinates
    p = {str(k).upper(): v for k, v in properties.items()}
    try:
        z = float(p.get(LAYERS[layer]))
    except (TypeError, ValueError):
        return np.empty((0, 3)), 'missing-elevation'
    if not math.isfinite(z) or not -500 <= z <= 9000:
        return np.empty((0, 3)), 'invalid-elevation'
    if geometry is None or geometry.is_empty:
        return np.empty((0, 3)), 'empty-geometry'
    if geometry.geom_type not in ({'LineString', 'MultiLineString'} if layer == 'N3L_F0010000' else {'Point', 'MultiPoint'}):
        return np.empty((0, 3)), 'wrong-geometry-type'
    xy = get_coordinates(geometry)
    if not np.isfinite(xy).all():
        return np.empty((0, 3)), 'invalid-coordinate'
    if native_bounds is not None:
        left,bottom,right,top=native_bounds
        xy=xy[(xy[:,0]>=left)&(xy[:,0]<=right)&(xy[:,1]>=bottom)&(xy[:,1]<=top)]
    x, y = transform(xy[:, 0], xy[:, 1])
    result = np.column_stack([x, y, np.full(len(xy), z)])
    if not np.isfinite(result).all():
        return np.empty((0, 3)), 'projection-failed'
    return result, None


def supported_tin(points, query, radius=1000, support_bounds=None):
    """Bounded local TIN; a 2*radius input halo makes accepted simplices tile-independent.

    Conflicting exact XY elevations are excluded rather than averaging unrelated
    measurements. Circumradius guards prevent distant geometry bridging holes.
    """
    import numpy as np
    from scipy.spatial import Delaunay, QhullError, cKDTree
    from scipy.interpolate import LinearNDInterpolator
    points = np.asarray(points, dtype='float64')
    points = points[np.isfinite(points).all(axis=1) & (points[:, 2] >= -500) & (points[:, 2] <= 9000)]
    points = np.unique(points, axis=0)
    _, inverse, counts = np.unique(points[:, :2], axis=0, return_inverse=True, return_counts=True)
    conflicts = int((counts > 1).sum())
    points = points[counts[inverse] == 1]
    values = np.full(len(query), np.nan)
    audit = {'uniqueSupportedVertices': len(points), 'conflictingCoordinates': conflicts}
    if len(points) < 3:
        return values, audit
    if len(points) > 2_000_000:
        raise ValueError('TIN point budget exceeded; subdivide the candidate job')
    try:
        tri = Delaunay(points[:, :2])
    except QhullError:
        return values, {**audit, 'degenerate': True}
    triangles = points[tri.simplices, :2]
    a = np.linalg.norm(triangles[:, 1] - triangles[:, 2], axis=1)
    b = np.linalg.norm(triangles[:, 0] - triangles[:, 2], axis=1)
    c = np.linalg.norm(triangles[:, 0] - triangles[:, 1], axis=1)
    ab, ac = triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]
    cross = np.abs(ab[:, 0]*ac[:, 1] - ab[:, 1]*ac[:, 0])
    radii = np.divide(a*b*c, 2*cross, out=np.full_like(a, np.inf), where=cross > 0)
    eligible = radii <= radius
    if support_bounds is not None:
        denominator = 2*(ab[:, 0]*ac[:, 1]-ab[:, 1]*ac[:, 0])
        ab2, ac2 = (ab*ab).sum(axis=1), (ac*ac).sum(axis=1)
        center_x = triangles[:, 0, 0]+(ab2*ac[:, 1]-ac2*ab[:, 1])/denominator
        center_y = triangles[:, 0, 1]+(ab[:, 0]*ac2-ac[:, 0]*ab2)/denominator
        left, bottom, right, top = support_bounds
        eligible &= (center_x-radii >= left) & (center_x+radii <= right)
        eligible &= (center_y-radii >= bottom) & (center_y+radii <= top)
    interpolator, tree = LinearNDInterpolator(tri, points[:, 2]), cKDTree(points[:, :2])
    for offset in range(0, len(query), 65536):
        coordinates = query[offset:offset + 65536]
        simplex = tri.find_simplex(coordinates)
        valid = (simplex >= 0) & eligible[np.maximum(simplex, 0)]
        valid &= np.isfinite(tree.query(coordinates, distance_upper_bound=radius)[0])
        block = interpolator(coordinates)
        block[~valid] = np.nan
        values[offset:offset + len(block)] = block
    return values, audit


def adaptive_tin(points, query, read_bounds=None):
    """Small fixed cores avoid one giant triangulation; accepted circles prove halo independence."""
    import numpy as np
    from scipy.spatial import cKDTree, ConvexHull, Delaunay, QhullError
    points = np.asarray(points, dtype='float64')
    points = points[np.isfinite(points).all(axis=1)]
    result = np.full(len(query), np.nan)
    if not len(points):
        return result, {'inputVertices': 0, 'budgetLimitedCells': 0}
    # A complete bounded patch can reuse one triangulation. The same circle
    # containment check proves that unseen source vertices cannot affect it.
    # Above the existing vertex cap, retain the bounded adaptive cores.
    if read_bounds is not None and len(points)<=2_000_000:
        result,audit=supported_tin(points,query,support_bounds=read_bounds)
        return result,{**audit,'inputVertices':len(points),'budgetLimitedCells':0,
                       'triangulationMode':'single-bounded-patch'}
    tree = cKDTree(points[:, :2]); budget_limited = 0
    eligible = np.isfinite(tree.query(query, distance_upper_bound=1000)[0])
    if np.any(eligible):
        try:
            hull = ConvexHull(points[:, :2])
            eligible &= Delaunay(points[hull.vertices, :2]).find_simplex(query) >= 0
        except QhullError:
            eligible[:] = False
    cells = np.floor(query/100).astype('int64')
    keys, inverse = np.unique(cells, axis=0, return_inverse=True)
    for index, (cx, cy) in enumerate(keys):
        pending = np.flatnonzero((inverse == index) & eligible)
        for halo in (100, 250, 500, 1000, 2000):
            if not len(pending):
                break
            bounds = (cx*100-halo, cy*100-halo, (cx+1)*100+halo, (cy+1)*100+halo)
            ids = tree.query_ball_point([cx*100+50, cy*100+50], (halo+50)*2**.5)
            local = points[ids]
            local = local[(local[:, 0] >= bounds[0]) & (local[:, 0] <= bounds[2])
                          & (local[:, 1] >= bounds[1]) & (local[:, 1] <= bounds[3])]
            if len(local) > 2_000_000:
                budget_limited += len(pending); break
            values, _ = supported_tin(local, query[pending], support_bounds=bounds)
            finite = np.isfinite(values)
            result[pending[finite]] = values[finite]
            pending = pending[~finite]
    return result, {'inputVertices': len(points), 'budgetLimitedCells': budget_limited,
                    'method': '100m fixed cores; adaptive halo; accepted circumcircles fully inside read halo'}


CENTERED_RECIPE = 'ngii-b021-cont-spot-centered-tin-5m-radius1000-v2'


def centered_tin(points, query, bounds):
    import numpy as np
    origin=np.floor(np.asarray(bounds[:2],dtype='float64')/1000)*1000
    shifted=np.asarray(points,dtype='float64').copy();shifted[:,:2]-=origin
    read_bounds=np.asarray([bounds[0]-2000,bounds[1]-2000,bounds[2]+2000,bounds[3]+2000])-np.tile(origin,2)
    values,audit=adaptive_tin(shifted,np.asarray(query)-origin,read_bounds=tuple(read_bounds))
    return values,{**audit,'coordinateOrigin5186':origin.tolist(),'kernel':CENTERED_RECIPE}


def write_patch(points, bounds, output, candidate_id, recipe=RECIPE):
    """Candidate-only 5 m patch, with real finite-cell coverage and no source mutation."""
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    left, bottom, right, top = bounds
    if any(value % 5 for value in bounds) or right <= left or top <= bottom:
        raise ValueError('Patch must align with the 5 m precision lattice')
    width, height = int((right-left)/5), int((top-bottom)/5)
    if width*height > 4_000_000:
        raise ValueError('Patch exceeds bounded raster budget')
    output = Path(output)
    reserve(output, width*height*4 + 1024*1024)
    if output.exists():
        raise ValueError('Candidate patches are immutable; resume through a verified receipt')
    gx, gy = np.meshgrid(left+(np.arange(width)+.5)*5, top-(np.arange(height)+.5)*5)
    points = np.asarray(points)
    # Bbox-filtered SHP records can contain entire contours extending far beyond
    # the job. Only the proven 2*support-radius halo participates in local TIN.
    points = points[(points[:, 0] >= left-2000) & (points[:, 0] <= right+2000)
                    & (points[:, 1] >= bottom-2000) & (points[:, 1] <= top+2000)]
    query=np.column_stack([gx.ravel(),gy.ravel()])
    if recipe==CENTERED_RECIPE:
        values,audit=centered_tin(points,query,bounds)
    elif recipe==RECIPE:
        values,audit=adaptive_tin(points,query)
    else:
        raise ValueError('Unknown terrain recipe')
    finite = np.isfinite(values)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix('.writing.tif')
    with rasterio.open(temporary, 'w', driver='GTiff', crs='EPSG:5186', transform=from_origin(left, top, 5, 5),
        width=width, height=height, count=1, dtype='float32', nodata=-9999, compress='deflate', tiled=True) as target:
        target.write(np.where(finite, values, -9999).reshape(height, width).astype('float32'), 1)
    receipt = {'schema': 'ngii-terrain-patch-v1', 'candidateId': candidate_id, 'recipe': recipe,
        'file': str(output.resolve()), 'sha256': sha(temporary.read_bytes()), 'bounds5186': list(bounds),
        'cells': len(values), 'finiteCells': int(finite.sum()), 'noDataCells': int((~finite).sum()),
        'finiteAreaSquareMetres': int(finite.sum())*25, **audit, 'activated': False}
    temporary.replace(output)
    output.with_suffix('.json').write_bytes(packed(receipt))
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--orders', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=os.environ.get('DATA_ROOT'))
    parser.add_argument('--precision-config', type=Path, required=True)
    args = parser.parse_args()
    if not args.data_root:
        parser.error('Explicit DATA_ROOT or --data-root is required')
    sources = plan_sources(args.orders)
    precision = json.loads(args.precision_config.read_text(encoding='utf8'))
    precision_root = args.precision_config.parent
    manifest = precision_root / precision['manifest']['path']
    if sha(manifest.read_bytes()) != precision['manifest']['sha256']:
        raise ValueError('Precision manifest changed')
    plan = {'schema': 'ngii-terrain-candidate-v1', 'recipe': RECIPE, **sources,
        'implementationSHA256': sha(Path(__file__).read_bytes()),
        'inputCRS': 'EPSG:5179', 'rasterCRS': 'EPSG:5186', 'resolutionMetres': 5,
        'supportRadiusMetres': 1000, 'requiredHaloMetres': 2000,
        'precision': {'config': str(args.precision_config.resolve()), 'configSHA256': sha(args.precision_config.read_bytes()),
                      'manifest': str(manifest.resolve()), 'manifestSHA256': sha(manifest.read_bytes()), 'rasters': len(precision['sources'])},
        'mergePolicy': 'finite original-sheet precision overrides B021 base; precision NoData preserves base',
        'heightContract': 'resolved-ancestor-grid-v1', 'activated': False}
    identity = sha(packed(plan)); plan['candidateId'] = identity
    output = args.data_root.resolve() / 'terrain-candidates' / identity
    reserve(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'plan.json').write_bytes(packed(plan))
    print(json.dumps({'candidateId': identity, 'output': str(output), 'sources': len(sources['sources']),
                      'expectedRows': sources['expectedRows'], 'precisionRasters': len(precision['sources']),
                      'state': 'planned-not-rasterized', 'activated': False}))


if __name__ == '__main__':
    main()
