"""Bounded priority terrain candidate jobs from the frozen official B021 cohort."""
import argparse
import importlib.util
import json
from pathlib import Path
import time
import numpy as np
import pyogrio
import rasterio
from rasterio.windows import from_bounds
import shapely
from pyproj import Transformer
from ngii_split_zip import stage_members
from ngii_spatial_index import build_qix
from ngii_terrain_candidate import elevation_points, write_patch, reserve, sha, packed, GIB


def overlaps(a, b):
    return a[0] <= b[2] and a[2] >= b[0] and a[1] <= b[3] and a[3] >= b[1]


def read_points(plan, bounds, stage_root, notify=lambda *_, **__: None):
    project = Transformer.from_crs(5179, 5186, always_xy=True)
    inverse = Transformer.from_crs(5186, 5179, always_xy=True)
    corners = np.array([inverse.transform(x, y) for x in [bounds[0]-2000, bounds[2]+2000]
                        for y in [bounds[1]-2000, bounds[3]+2000]])
    bbox = [*corners.min(axis=0), *corners.max(axis=0)]
    native_halo=[bbox[0]-5,bbox[1]-5,bbox[2]+5,bbox[3]+5]
    points, reports, total = [], [], 0
    for source in plan['sources']:
        if not overlaps(source['bounds5179'], bbox):
            continue
        notify('reading-source',source=source['id'],member=source['shp'])
        source_started=time.monotonic(); index_seconds=0
        disks = [Path(binding['path']) for binding in source['bindings']]
        for disk, binding in zip(disks, source['bindings']):
            stat = disk.stat()
            if (stat.st_size, stat.st_mtime_ns) != (binding['bytes'], binding['mtimeNs']):
                raise ValueError('Official source changed since frozen plan')
        if len(disks) > 1:
            stage = stage_root / source['id']; receipt = stage / 'stage.json'
            if receipt.exists():
                saved = json.loads(receipt.read_text())
                for name, stamp in saved['members'].items():
                    stat = (stage/name).stat()
                    if [stat.st_size, stat.st_mtime_ns] != stamp:
                        raise ValueError('Staged member changed')
            else:
                stem = source['shp'][:-4]; wanted = [stem+ext for ext in ['.shp', '.shx', '.dbf', '.prj']]
                stage_members(disks, stage, wanted, 20*GIB)
                receipt.write_bytes(packed({'source': source['id'], 'members': {
                    name: [(stage/name).stat().st_size, (stage/name).stat().st_mtime_ns] for name in wanted}}))
            uri = str(stage/source['shp'])
            notify('indexing-staged-source',source=source['id'])
            index_started=time.monotonic()
            build_qix(Path(uri),stage_root,source['field'],bbox)
            index_seconds=time.monotonic()-index_started
            notify('reading-source',source=source['id'],member=source['shp'])
        else:
            uri = f'zip://{disks[0].as_posix()}!{source["shp"]}'
        rows = vertices = 0; rejected = {}
        with pyogrio.open_arrow(uri, columns=[source['field']], bbox=tuple(bbox), batch_size=1000, use_pyarrow=True) as (meta, reader):
            geometry_column = meta.get('geometry_name') or 'wkb_geometry'
            for batch in reader:
                reserve(stage_root)
                data = batch.to_pydict(); geometries = shapely.from_wkb(data[geometry_column])
                for index, geometry in enumerate(geometries):
                    rows += 1
                    values, reason = elevation_points({source['field']: data[source['field']][index]}, geometry, source['layer'], project.transform,native_halo)
                    if reason:
                        rejected[reason] = rejected.get(reason, 0)+1; continue
                    values = values[(values[:, 0] >= bounds[0]-2000) & (values[:, 0] <= bounds[2]+2000)
                                    & (values[:, 1] >= bounds[1]-2000) & (values[:, 1] <= bounds[3]+2000)]
                    vertices += len(values); total += len(values)
                    if total > 2_000_000:
                        raise ValueError('Target source buffer cap exceeded; subdivide target job')
                    points.append(values)
        reports.append({'source': source['id'], 'rowsRead': rows, 'retainedVertices': vertices, 'rejected': rejected,
                        'elapsedSeconds':time.monotonic()-source_started,'indexSeconds':index_seconds})
        notify('source-read',source=source['id'],rows=rows,vertices=vertices)
    return np.vstack(points) if points else np.empty((0, 3)), reports


def merge_precision(base, output, config_path, expected_sha):
    config_path = Path(config_path)
    if sha(config_path.read_bytes()) != expected_sha:
        raise ValueError('Active precision configuration changed; prepare a new candidate')
    config = json.loads(config_path.read_text())
    manifest_path = config_path.parent/config['manifest']['path']
    if sha(manifest_path.read_bytes()) != config['manifest']['sha256']:
        raise ValueError('Precision manifest changed')
    manifest = json.loads(manifest_path.read_text())
    expected = {str((manifest_path.parent/row['path']).resolve()): row['sha256'] for row in manifest['sources']}
    if set(expected) != {str((config_path.parent/name).resolve()) for name in config['sources']}:
        raise ValueError('Precision source set differs from verified manifest')
    saved = output.with_suffix('.json')
    if output.exists():
        if not saved.exists():
            raise ValueError('Incomplete layered patch requires a fresh candidate path')
        receipt = json.loads(saved.read_text())
        if receipt['sha256'] != sha(output.read_bytes()) or receipt['configSHA256'] != expected_sha:
            raise ValueError('Layered candidate changed')
        return receipt
    with rasterio.open(base) as source:
        profile = source.profile; values = source.read(1); bounds = source.bounds; transform = source.transform
        base_valid = np.isfinite(values) & (values != source.nodata)
    used = []; overwritten = 0
    for name in config['sources']:
        path = config_path.parent/name
        with rasterio.open(path) as precision:
            if not overlaps(precision.bounds, bounds):
                continue
            digest = sha(path.read_bytes())
            if digest != expected[str(path.resolve())]:
                raise ValueError('Verified precision raster changed')
            if precision.crs != profile['crs'] or precision.res != (5, 5):
                raise ValueError('Precision grid differs from candidate')
            window = from_bounds(*bounds, transform=precision.transform)
            if abs(window.col_off-round(window.col_off)) > 1e-6 or abs(window.row_off-round(window.row_off)) > 1e-6:
                raise ValueError('Precision grid is not aligned')
            data = precision.read(1, window=window, boundless=True, masked=True)
            valid = ~np.ma.getmaskarray(data) & np.isfinite(data.data) & (data.data >= -500) & (data.data <= 9000)
            values[valid] = data.data[valid]; overwritten += int(valid.sum())
            used.append({'path': str(path), 'sha256': digest, 'finiteCells': int(valid.sum())})
    if np.any(base_valid & (~np.isfinite(values) | (values == profile['nodata']))):
        raise ValueError('Precision erased finite base')
    reserve(output, values.nbytes)
    if output.exists():
        raise ValueError('Immutable layered patch already exists')
    with rasterio.open(output, 'w', **profile) as target:
        target.write(values, 1)
    receipt = {'sources': used, 'precisionFiniteCellWrites': overwritten, 'sha256': sha(output.read_bytes()), 'configSHA256': expected_sha}
    saved.write_bytes(packed(receipt))
    return receipt


def run(plan_path, priority_path, index):
    plan_path = Path(plan_path); root = plan_path.parent
    plan = json.loads(plan_path.read_text(encoding='utf8')); priority = json.loads(Path(priority_path).read_text(encoding='utf8'))
    if sha(Path(priority['points']).read_bytes()) != priority['sha256']:
        raise ValueError('Frozen target cohort changed')
    job = priority['jobs'][index]
    folder = root/'target-patches'/('-'.join(map(str, job['cell'])))
    folder.mkdir(parents=True, exist_ok=True)
    if (folder/'result.json').exists():
        return json.loads((folder/'result.json').read_text())
    bounds = [job['bounds5186'][0]-10, job['bounds5186'][1]-10, job['bounds5186'][2]+10, job['bounds5186'][3]+10]
    started = time.monotonic()
    def phase(name,**extra):
        temporary=root/'job-phase.next'
        temporary.write_bytes(packed({'index':index,'cell':job['cell'],'phase':name,'at':time.time(),**extra}))
        temporary.replace(root/'job-phase.json')
    points, source_reports = read_points(plan, bounds, Path(plan.get('stageRoot', root/'stage')),phase)
    source_finished=time.monotonic()
    phase('rasterizing',vertices=len(points))
    base = folder/'base.tif'
    if base.exists():
        receipt = json.loads(base.with_suffix('.json').read_text())
        if sha(base.read_bytes()) != receipt['sha256'] or receipt['candidateId'] != plan['candidateId']:
            raise ValueError('Candidate base changed')
    else:
        receipt = write_patch(points, bounds, base, plan['candidateId'],recipe=plan['recipe'])
    if receipt['budgetLimitedCells']:
        raise ValueError('Budget-limited candidate needs subdivision before coverage accounting')
    layered = folder/'layered.tif'
    phase('merging-precision')
    tin_finished=time.monotonic()
    merged = merge_precision(base, layered, plan['precision']['config'], plan['precision']['configSHA256'])
    precision_finished=time.monotonic()
    sampler_path = Path(__file__).resolve().parents[2]/'frontend/app/editor/tools/sample-building-dem.py'
    spec = importlib.util.spec_from_file_location('candidate_sampler', sampler_path)
    sampler = importlib.util.module_from_spec(spec); spec.loader.exec_module(sampler)
    records = {row['key']: row for row in json.loads(Path(priority['points']).read_text())}
    selected = [records[key] for key in job['targetKeys']]
    phase('sampling-targets',targets=len(selected))
    values = sampler.sample(str(layered), [row['point'] for row in selected])['heights']
    result = {'schema': 'ngii-target-terrain-result-v1', 'candidateId': plan['candidateId'],
        'cohortSHA256': priority['sha256'], 'targetCount': len(selected),
        'filledKeys': [row['key'] for row, value in zip(selected, values) if value is not None],
        'unfilledKeys': [row['key'] for row, value in zip(selected, values) if value is None],
        'base': receipt, 'precision': merged, 'sourceReports': source_reports,
        'phaseSeconds':{'source':source_finished-started,'tin':tin_finished-source_finished,
                        'precision':precision_finished-tin_finished,'sampling':time.monotonic()-precision_finished},
        'elapsedSeconds': time.monotonic()-started, 'activated': False}
    (folder/'result.json').write_bytes(packed(result))
    return {k: v for k, v in result.items() if k not in ('filledKeys','unfilledKeys','sourceReports','base','precision')} | {
        'filled': len(result['filledKeys']), 'unfilled': len(result['unfilledKeys']), 'path': str(folder/'result.json')}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True); parser.add_argument('--priority', type=Path, required=True)
    parser.add_argument('--index', type=int, default=0)
    args = parser.parse_args(); print(json.dumps(run(args.plan, args.priority, args.index)))
