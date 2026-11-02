"""Precision staging policy; missing-building counts remain separate from terrain coverage."""
import os
import json
from pathlib import Path
import numpy as np


def load_source_list(path,root):
    if path is None:return None
    names=json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(names,list) or not names or any(not isinstance(name,str) or not name or Path(name).name!=name or '/' in name or '\\' in name or ':' in name for name in names):
        raise ValueError('Source list must contain source filenames only')
    if len(set(names))!=len(names):raise ValueError('Duplicate source filename')
    for name in names:
        source=root/'files'/name
        if source.suffix.lower() not in ('.dxf','.zip','.ngi') or not source.is_file() or not source.with_suffix(source.suffix+'.receipt.json').is_file():
            raise ValueError('Unknown or unreceipted source: '+name)
    return set(names)


def attribute_companion_arrived(name,result,root):
    if Path(name).suffix.lower()!='.ngi' or result.get('state')!='failed' or result.get('errorType')!='FileNotFoundError':return False
    source=root/'files'/name;attribute=source.with_suffix('.nda')
    return all(path.is_file() for path in (source,source.with_suffix('.ngi.receipt.json'),attribute,attribute.with_suffix('.nda.receipt.json')))


def should_retry(state, refine_existing):
    return refine_existing and state in {'no_known_missing_point_in_sheet', 'no_missing_point_supported', 'no_precise_catalogue_match'}


def may_stage(missing_count, refine_existing):
    return missing_count > 0 or refine_existing


def supported_values(interpolator, tree, coordinates):
    values = interpolator(coordinates)
    values[~np.isfinite(tree.query(coordinates, distance_upper_bound=1000)[0])] = np.nan
    return values


def acquire_stage_lock(path):
    stream = path.open('a+b')
    try:
        if os.fstat(stream.fileno()).st_size == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except Exception:
        stream.close()
        raise
    return stream
