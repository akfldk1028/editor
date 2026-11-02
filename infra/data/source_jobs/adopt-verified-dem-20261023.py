"""Adopt source-equivalent regional rasters while the national writer is stopped."""
import source_job_paths as sjp
import hashlib
import json
import shutil
from pathlib import Path

root = Path(str(sjp.NGII_DEM_ROOT))
audit_path = sjp.INDEX_STATE_ROOT / 'dem-reuse-verified-20261023.json'
audit = json.loads(audit_path.read_text(encoding='utf-8'))
assert audit['state'] == 'complete' and audit['source_unchanged_at_end']
assert audit['old_build_unchanged_at_end'] and audit['archive_stats_stable_at_end']
assert audit['all_old_valid_cell_counts_match'] and not audit['rejected']


def verify_file(record, *, digest=False):
    path = Path(record['file'])
    stat = path.stat()
    assert (stat.st_size, stat.st_mtime_ns) == (record['bytes'], record['mtime_ns']), path
    if digest:
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record['sha256'], path


for record in audit['national_source_components']:
    verify_file(record)
for archive in audit['old_archive_checks']:
    verify_file(archive)
    assert all(c['matches'] and c['installed_crc32'] == c['zip_crc32'] for c in archive['components'])
verify_file(audit['old_build'], digest=True)
audit_sha = hashlib.sha256(audit_path.read_bytes()).hexdigest()
adopted, skipped = [], []
for row in audit['verified']:
    x,y = row['block']
    name = f'zznational_{x}_{y}'
    target = root/'blocks'/f'{name}.tif'
    receipt = root/'national-receipts'/f'{name}.json'
    if receipt.exists() and target.exists():
        skipped.append([x,y])
        continue
    assert row['upper_boundary_points'] == 0 and row['old_points'] == row['current_points']
    assert row['old_archives_predate_raster'] and row['old_valid_cells_match_receipt']
    verify_file(row['old_raster'], digest=True)
    temporary = root/'national-work'/f'{name}.adopt.tif'
    shutil.copy2(row['old_raster']['file'], temporary)
    assert hashlib.sha256(temporary.read_bytes()).hexdigest() == row['old_raster']['sha256']
    temporary.replace(target)
    result = {'block':[x,y], 'status':'ok', 'points':row['current_points'],
              'valid_cells':row['old_valid_cells'], 'signature':audit['national_source_signature'],
              'sources':row['sources'], 'kind':'derived', 'resolution_m':5,
              'method':'NGII contours and spot heights; padded Delaunay TIN; voids remain NoData',
              'reused_from':row['old_raster'], 'points_sha256':row['points_sha256'],
              'reuse_audit':{'file':str(audit_path),'sha256':audit_sha,'limitations':audit['limitations']}}
    temporary = receipt.with_suffix('.tmp')
    temporary.write_text(json.dumps(result),encoding='utf-8')
    temporary.replace(receipt)
    adopted.append([x,y])
report = {'adopted':adopted,'skipped':skipped,'audit_sha256':audit_sha}
audit_path.with_name('dem-reuse-adopted-20261023.json').write_text(json.dumps(report),encoding='utf-8')
print(json.dumps({'adopted':len(adopted),'skipped':len(skipped)}))
