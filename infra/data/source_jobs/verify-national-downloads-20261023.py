import source_job_paths as sjp
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

root = sjp.INDEX_STATE_ROOT
audit = json.loads((root / 'national-source-audit-20261023.json').read_text(encoding='utf-8'))
receipt = root / 'national-download-receipt-20261023.json'
previous = json.loads(receipt.read_text(encoding='utf-8')) if receipt.exists() else {}
old = {r['path']: r for r in previous.get('files', [])}
rows = []
for row in audit['files']:
    path = Path(row['path'])
    result = dict(row)
    if not path.is_file():
        result['state'] = 'missing'
    else:
        stat = path.stat()
        result.update(bytes=stat.st_size, mtime_ns=stat.st_mtime_ns)
        prior = old.get(str(path), {})
        if prior.get('state') == 'zip_crc_verified' and prior.get('bytes') == stat.st_size and prior.get('mtime_ns') == stat.st_mtime_ns:
            result = prior
        else:
            try:
                if abs(stat.st_size // 1024 - row['size_kb']) > 1:
                    raise ValueError('size differs from catalogue')
                with zipfile.ZipFile(path) as archive:
                    bad = archive.testzip()
                    if bad:
                        raise ValueError('CRC failure: ' + bad)
                    result['members'] = len(archive.infolist())
                    result['uncompressed_bytes'] = sum(m.file_size for m in archive.infolist())
                result['state'] = 'zip_crc_verified'
            except Exception as error:
                result['state'] = 'failed_validation'
                result['error'] = str(error)
    rows.append(result)
    summary = {state: sum(r['state'] == state for r in rows) for state in sorted({r['state'] for r in rows})}
    payload = {'checkedAt': datetime.now(timezone.utc).isoformat(), 'scope': 'Seven audited nationwide layers; ZIP validation is not installation or rendered coverage', 'summary': summary, 'files': rows}
    temporary = receipt.with_suffix('.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(receipt)
    print(result['state'], row['name'], flush=True)
print(summary, flush=True)
