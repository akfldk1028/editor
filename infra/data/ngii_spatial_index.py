"""Create a GDAL QIX only beside verified, derived staging SHP files."""
import ctypes
import hashlib
import json
from pathlib import Path
import re
import time
import pyogrio
from ngii_terrain_candidate import reserve, packed


def digest_file(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def bbox_digest(path,field,bounds):
    started=time.perf_counter();rows=[]
    with pyogrio.open_arrow(str(path),columns=[field],bbox=tuple(bounds),batch_size=1000,use_pyarrow=True) as (meta,reader):
        geometry=meta.get('geometry_name') or 'wkb_geometry'
        for batch in reader:
            data=batch.to_pydict()
            for shape,value in zip(data[geometry],data[field]):
                rows.append(hashlib.sha256((shape or b'')+packed(value)).digest())
    return {'rows':len(rows),'sha256':hashlib.sha256(b''.join(sorted(rows))).hexdigest(),'seconds':time.perf_counter()-started}


def build_qix(path,stage_root,field,bounds):
    path,stage_root=Path(path).resolve(),Path(stage_root).resolve()
    if stage_root.name!='stage' or not path.is_relative_to(stage_root) or path.suffix.lower()!='.shp':
        raise ValueError('Spatial indexes are restricted to derived staging SHPs')
    if not re.fullmatch(r'[A-Za-z0-9_]+',path.stem):
        raise ValueError('Unsafe GDAL layer identifier')
    qix=path.with_suffix('.qix');proof_path=path.with_suffix('.qix.json')
    if qix.exists():
        if not proof_path.exists():raise ValueError('Existing QIX lacks a verified receipt')
        proof=json.loads(proof_path.read_text())
        if digest_file(qix)!=proof['qixSHA256']:raise ValueError('Spatial index changed')
        return proof
    reserve(path,16*1024*1024)
    source_paths=[path.with_suffix(ext) for ext in ['.shp','.shx','.dbf','.prj']]
    before_files={str(p):digest_file(p) for p in source_paths}
    before=bbox_digest(path,field,bounds)
    libraries=list((Path(pyogrio.__file__).parent.parent/'pyogrio.libs').glob('*gdal*.dll'))
    if len(libraries)!=1:raise RuntimeError('Expected the one GDAL library already loaded by pyogrio')
    lib=ctypes.CDLL(str(libraries[0]))
    lib.GDALOpenEx.argtypes=[ctypes.c_char_p,ctypes.c_uint,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p];lib.GDALOpenEx.restype=ctypes.c_void_p
    lib.GDALDatasetExecuteSQL.argtypes=[ctypes.c_void_p,ctypes.c_char_p,ctypes.c_void_p,ctypes.c_char_p];lib.GDALDatasetExecuteSQL.restype=ctypes.c_void_p
    lib.GDALDatasetReleaseResultSet.argtypes=[ctypes.c_void_p,ctypes.c_void_p]
    lib.GDALClose.argtypes=[ctypes.c_void_p]
    lib.CPLErrorReset.argtypes=[];lib.CPLGetLastErrorType.restype=ctypes.c_int;lib.CPLGetLastErrorMsg.restype=ctypes.c_char_p
    handle=lib.GDALOpenEx(str(path).encode('utf8'),5,None,None,None) # VECTOR | UPDATE
    if not handle:raise RuntimeError('Could not open derived SHP for indexing')
    started=time.perf_counter()
    try:
        lib.CPLErrorReset()
        result=lib.GDALDatasetExecuteSQL(handle,f'CREATE SPATIAL INDEX ON {path.stem}'.encode(),None,None)
        if result:lib.GDALDatasetReleaseResultSet(handle,result)
        if lib.CPLGetLastErrorType()>=3:raise RuntimeError(lib.CPLGetLastErrorMsg().decode('utf8','replace'))
    finally:lib.GDALClose(handle)
    build_seconds=time.perf_counter()-started
    if not qix.is_file():raise ValueError('GDAL did not create QIX')
    after=bbox_digest(path,field,bounds)
    if (before['rows'],before['sha256'])!=(after['rows'],after['sha256']):raise ValueError('Index changed bbox feature results')
    if before_files!={str(p):digest_file(p) for p in source_paths}:raise ValueError('Index creation modified source feature bytes')
    proof={'schema':'ngii-derived-qix-v1','path':str(path),'sourceSHA256':before_files,'qixSHA256':digest_file(qix),
        'qixBytes':qix.stat().st_size,'field':field,'bbox':list(bounds),'before':before,'after':after,'buildSeconds':build_seconds,
        'gdalVersion':list(pyogrio.__gdal_version__),'rawZipChanged':False}
    proof_path.write_bytes(packed(proof));return proof
