"""Explicit, atomic import of validated provider caches; dry runs never create storage."""
from contextlib import closing
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import sqlite3

from shapely.geometry import shape


def _object(pairs):
    result={}
    for key,value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key]=value
    return result


def _invalid_constant(value):
    raise ValueError('Nonfinite JSON constant')


def _timestamp(value):
    if not isinstance(value,str):
        raise ValueError('Invalid timestamp')
    stamp=datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError('Timestamp requires timezone')
    return stamp


def _zone_geometry(value):
    if not isinstance(value,dict) or value.get('type') not in ('Polygon','MultiPolygon'):
        raise ValueError('Invalid zone geometry')
    polygons=[value.get('coordinates')] if value['type']=='Polygon' else value.get('coordinates')
    if not isinstance(polygons,list) or not polygons:
        raise ValueError('Missing zone coordinates')
    for polygon in polygons:
        if not isinstance(polygon,list) or not polygon:
            raise ValueError('Missing zone ring')
        for ring in polygon:
            if not isinstance(ring,list) or len(ring)<4 or ring[0]!=ring[-1]:
                raise ValueError('Invalid zone ring')
            for point in ring:
                if not isinstance(point,list) or len(point)!=2 or any(type(n) not in (int,float) or not math.isfinite(n) for n in point):
                    raise ValueError('Invalid zone coordinate')
                if not (-180<=point[0]<=180 and -90<=point[1]<=90):
                    raise ValueError('Zone coordinate outside WGS84')
    # Provider zone layers can have self-intersections outside the queried parcel.
    # Preserve those raw features: the existing intersection pipeline owns topology handling.
    shape(value)


def _record(repository,kind,path,raw):
    payload=json.loads(raw,object_pairs_hook=_object,parse_constant=_invalid_constant)
    if not isinstance(payload,dict):
        raise ValueError('Cache must be an object')
    timestamp=payload['fetched_at'];_timestamp(timestamp)
    if kind=='land':
        result=payload['result'];key=path.stem
        repository._validate_land_cache(key,result)
    else:
        bounds=payload['bounds'];layer=payload['layer'];result=payload['features']
        if layer!='LT_C_UQ111':
            raise ValueError('Unsupported zone layer')
        if not isinstance(bounds,list) or len(bounds)!=4 or any(type(n) not in (int,float) or not math.isfinite(n) for n in bounds):
            raise ValueError('Invalid bounds')
        bounds=[float(n) for n in bounds]
        if not (-180<=bounds[0]<bounds[2]<=180 and -90<=bounds[1]<bounds[3]<=90):
            raise ValueError('Invalid WGS84 bounds')
        old_key=hashlib.sha256((layer+'|'+','.join(f'{n:.6f}' for n in bounds)).encode()).hexdigest()[:16]
        if path.stem!=old_key:
            raise ValueError('Zone identity mismatch')
        if not isinstance(result,list) or not result:
            raise ValueError('Missing zone features')
        for feature in result:
            if not isinstance(feature,dict) or feature.get('type')!='Feature' or (feature.get('properties') is not None and not isinstance(feature.get('properties'),dict)):
                raise ValueError('Invalid feature')
            _zone_geometry(feature.get('geometry'))
        # GeometryQueries hashes the unrounded bounds of the selected Shapely polygon.
        key=hashlib.sha256(json.dumps([layer,bounds]).encode()).hexdigest()
    return key,timestamp,json.dumps(result,ensure_ascii=False,allow_nan=False)


def _existing(db,kind,key):
    table,column=('land_cache','pnu') if kind=='land' else ('zone_cache','cache_key')
    if db is None or not db.execute('SELECT 1 FROM sqlite_master WHERE type=? AND name=?',('table',table)).fetchone():
        return None
    row=db.execute(f'SELECT fetched_at FROM {table} WHERE {column}=?',(key,)).fetchone()
    return row[0] if row else None


def _apply(db,records,report,write):
    for kind,entries in records.items():
        counts=report[kind]
        for key,timestamp,value in entries:
            existing=_existing(db,kind,key)
            if existing is not None and _timestamp(existing)>=_timestamp(timestamp):
                counts['skip_newer']+=1
                continue
            counts['update' if existing is not None else 'insert']+=1
            if write:
                table,column,data=('land_cache','pnu','result_json') if kind=='land' else ('zone_cache','cache_key','features_json')
                db.execute(f'INSERT INTO {table} VALUES (?,?,?) ON CONFLICT({column}) DO UPDATE SET '
                           f'fetched_at=excluded.fetched_at,{data}=excluded.{data}',(key,timestamp,value))
                counts['imported']+=1


def import_caches(repository,land_dir=None,zone_dir=None,*,dry_run=True):
    if type(dry_run) is not bool:
        raise ValueError('dry_run must be boolean')
    report={'dry_run':dry_run,'valid':True,'rejected':[]}
    records={'land':[],'zone':[]};digest=hashlib.sha256()
    for kind,directory in [('land',land_dir),('zone',zone_dir)]:
        report[kind]={'selected':0,'insert':0,'update':0,'skip_newer':0,'imported':0}
        if directory is None:
            continue
        directory=Path(directory)
        if not directory.is_dir():
            report['rejected'].append({'kind':kind,'index':None,'reason':'Source directory unavailable'})
            continue
        files=sorted(directory.glob('*.json'));report[kind]['selected']=len(files)
        identities=set()
        for index,path in enumerate(files):
            try:
                if path.is_symlink() or not path.is_file():
                    raise ValueError('Not a regular source file')
                raw=path.read_bytes()
                digest.update(kind.encode()+b'\0'+path.name.encode()+b'\0'+raw+b'\0')
                record=_record(repository,kind,path,raw)
                if record[0] in identities:
                    raise ValueError('Duplicate cache identity')
                identities.add(record[0]);records[kind].append(record)
            except (ValueError,TypeError,KeyError,AttributeError,OSError,OverflowError):
                report['rejected'].append({'kind':kind,'index':index,'reason':'Invalid cache record'})
    report['source_sha256']=digest.hexdigest()
    if report['rejected']:
        report['valid']=False
        return report
    if dry_run:
        if repository.path.exists():
            with closing(sqlite3.connect(repository.path.as_uri()+'?mode=ro',uri=True)) as db:
                _apply(db,records,report,False)
        else:
            _apply(None,records,report,False)
    elif any(records.values()):
        with repository._transaction() as db:
            _apply(db,records,report,True)
    return report
