"""Read measured NGII contour and spot entities without treating meshes as contours."""
from pathlib import Path
import numpy as np

PARSER_VERSION='dxf-polyline-v2'


def needs_reparse(name,result):
    return Path(name).suffix.lower()=='.dxf' and result.get('parserVersion')!=PARSER_VERSION


def raster_name(sheet,source_hash,name):
    suffix='-'+PARSER_VERSION if Path(name).suffix.lower()=='.dxf' else ''
    return sheet+'-'+source_hash[:12]+suffix+'.tif'


def parse_elevation(doc):
    chunks=[];contours=spots=0
    for entity in doc.modelspace():
        layer=entity.dxf.layer;kind=entity.dxftype()
        if layer.startswith('F001'):
            if kind=='LWPOLYLINE' and entity.dxf.hasattr('elevation'):
                vertices=entity.vertices_in_wcs()
            elif kind=='POLYLINE' and not entity.is_polygon_mesh and not entity.is_poly_face_mesh and (entity.is_2d_polyline or entity.is_3d_polyline):
                vertices=entity.points_in_wcs()
            else:
                continue
            xyz=np.asarray(list(vertices),dtype=float)
            if len(xyz):chunks.append(xyz);contours+=1
        elif layer.startswith('F002') and kind=='INSERT':
            chunks.append(np.array(entity.dxf.insert,dtype=float).reshape(1,3));spots+=1
    return chunks,contours,spots
