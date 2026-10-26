"""Array geometry acceleration with the scalar adapter retained for nonstandard geometry."""
import hashlib
import json
import numpy as np
import shapely


def adapt_batch(adapter, records):
    records=list(records)
    if not records:
        return []
    geometries=np.asarray([r[2] for r in records],dtype=object)
    valid=shapely.is_valid(geometries)
    types=shapely.get_type_id(geometries)
    fast=valid & np.isin(types,[3,6]) & ~shapely.is_empty(geometries)
    coordinates,index=shapely.get_coordinates(geometries,return_index=True)
    if len(coordinates):
        fast[np.unique(index[~np.isfinite(coordinates).all(axis=1)])]=False
    chosen=np.flatnonzero(fast)
    output=[None]*len(records)
    if len(chosen):
        normalized=shapely.normalize(shapely.make_valid(shapely.force_2d(geometries[chosen]),method='structure',keep_collapsed=False))
        projected=shapely.transform(normalized,adapter.project,interleaved=False)
        if not np.isfinite(shapely.bounds(projected)).all():
            raise ValueError('Source geometry cannot be projected')
        encoded=shapely.to_wkb(normalized,byte_order=1,output_dimension=2)
        geojson=shapely.to_geojson(projected)
        areas=shapely.area(normalized);parts=shapely.get_num_geometries(normalized)
        anchors=shapely.point_on_surface(projected);xs=shapely.get_x(anchors);ys=shapely.get_y(anchors)
        for j,i in enumerate(chosen):
            row,properties,_=records[i]
            audit={'geometrySHA256':hashlib.sha256(encoded[j]).hexdigest(),'areaM2':float(areas[j]),
                   'repaired':False,'parts':int(parts[j])}
            output[i]=adapter.record(properties,audit,json.loads(geojson[j]),[float(xs[j]),float(ys[j])],row=row)
    for i in np.flatnonzero(~fast):
        row,properties,geometry=records[i]
        output[i]=adapter.adapt(properties,geometry,row=row)
    return output
