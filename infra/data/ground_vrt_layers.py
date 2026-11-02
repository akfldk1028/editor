"""Prepare immutable ground candidates; precision NoData never erases the base."""
import argparse,hashlib,json,xml.etree.ElementTree as ET
from pathlib import Path
import rasterio
from rasterio.windows import from_bounds
from release_store import atomic_json,digest
from source_jobs.ngii_dxf import PARSER_VERSION as DXF_PARSER_VERSION

def freeze_vrt(source,target):
    tree=ET.fromstring(source.read_bytes())
    for node in tree.iter('SourceFilename'):
        path=Path(node.text)
        if node.get('relativeToVRT')=='1':path=source.parent/path
        node.text=str(path.resolve());node.set('relativeToVRT','0')
    target.write_bytes(ET.tostring(tree))

def compose(base,precision,output,*,precision_only=False):
    with rasterio.open(base) as src:
        tree=ET.Element('VRTDataset',rasterXSize=str(src.width),rasterYSize=str(src.height))
        ET.SubElement(tree,'SRS').text=src.crs.to_wkt()
        ET.SubElement(tree,'GeoTransform').text=','.join(map(str,src.transform.to_gdal()))
        band=ET.SubElement(tree,'VRTRasterBand',dataType='Float32',band='1')
        ET.SubElement(band,'NoDataValue').text='-9999'
        for path in ([] if precision_only else [base])+list(precision):
            with rasterio.open(path) as patch:
                if patch.crs!=src.crs or patch.res!=src.res or patch.transform.b or patch.transform.d:raise ValueError('Ground grid CRS/resolution mismatch')
                window=from_bounds(*patch.bounds,transform=src.transform)
                if any(abs(v-round(v))>1e-6 for v in (window.col_off,window.row_off,window.width,window.height)):raise ValueError('Ground grid alignment mismatch')
                if window.col_off<0 or window.row_off<0 or window.col_off+window.width>src.width or window.row_off+window.height>src.height:raise ValueError('Precision source outside base extent')
                if patch.nodata is None:raise ValueError('Explicit source NoData required')
                node=ET.SubElement(band,'ComplexSource')
                ET.SubElement(node,'SourceFilename',relativeToVRT='0').text=str(path.resolve())
                ET.SubElement(node,'SourceBand').text='1';ET.SubElement(node,'NODATA').text=str(patch.nodata)
                ET.SubElement(node,'SrcRect',xOff='0',yOff='0',xSize=str(patch.width),ySize=str(patch.height))
                ET.SubElement(node,'DstRect',xOff=str(round(window.col_off)),yOff=str(round(window.row_off)),xSize=str(patch.width),ySize=str(patch.height))
    output.parent.mkdir(parents=True,exist_ok=True);output.write_bytes(ET.tostring(tree))

def prepare(base,originals,output_root,additional_originals=()):
    rows=[]
    for node in ET.fromstring(base.read_bytes()).iter('SourceFilename'):
        path=Path(node.text)
        if node.get('relativeToVRT')=='1':path=base.parent/path
        if path.name.startswith('original_patch_'):
            rows.append({'name':path.name,'path':str(path.resolve()),'sha256':digest(path),'scale':5000,'priority':0,'provenance':'previously installed original-source patch'})
    for source_root in [originals,*additional_originals]:
        report=json.loads((source_root/'terrain-stage-status.json').read_text(encoding='utf8'))
        for name,row in report['results'].items():
            if row.get('state')!='staged':continue
            if Path(name).suffix.lower()=='.dxf' and row.get('parserVersion')!=DXF_PARSER_VERSION:
                raise ValueError('Staged DXF requires current parser version: '+name)
            path=Path(row['file']);original=source_root/'files'/name
            if original.name!=name or digest(original)!=row['sourceSHA256']:raise ValueError('Original source verification failed')
            if row.get('attributeSource'):
                attribute=source_root/'files'/row['attributeSource']
                if attribute.name!=row['attributeSource'] or digest(attribute)!=row['attributeSHA256']:raise ValueError('Original attribute verification failed')
            rows.append({'name':name,'path':str(path.resolve()),'sha256':digest(path),'originalSHA256':row['sourceSHA256'],'scale':int(row['scale']),'priority':1,
                **({'parserVersion':row['parserVersion']} if row.get('parserVersion') else {})})
    rows.sort(key=lambda r:(r['priority'],-r['scale'],r['name'].split('_')[2],r['name']))
    identity=hashlib.sha256(json.dumps({'base':digest(base),'precision':rows},sort_keys=True).encode()).hexdigest()
    output=output_root/identity
    if (output/'manifest.json').exists():return json.loads((output/'manifest.json').read_text(encoding='utf8'))
    output.mkdir(parents=True,exist_ok=True)
    frozen=output/'base.vrt';freeze_vrt(base,frozen)
    precision=[Path(r['path']) for r in rows]
    compose(frozen,precision,output/'precision.vrt',precision_only=True)
    compose(frozen,precision,output/'layered.vrt')
    manifest={'schema':'ground-layers-v1','revision':identity,'base':str(frozen),'precision':str(output/'precision.vrt'),'layered':str(output/'layered.vrt'),'sources':rows,'policy':'valid precision overrides base; precision NoData preserves base','activated':False}
    atomic_json(output/'manifest.json',manifest);return manifest

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--base',type=Path,required=True);p.add_argument('--originals',type=Path,required=True);p.add_argument('--additional-originals',type=Path,action='append',default=[]);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=prepare(a.base,a.originals,a.output,a.additional_originals)
    print(json.dumps({k:v for k,v in result.items() if k!='sources'}))
