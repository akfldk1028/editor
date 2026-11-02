"""Install only original-source patches, preserving every existing valid raster cell."""
import source_job_paths as sjp
import json, shutil, time, xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np
import rasterio
from rasterio.windows import from_bounds

ROOT=Path(str(sjp.NGII_DEM_ROOT))
live=ROOT/'ngii_dem.vrt'
original=live.read_bytes()
tree=ET.fromstring(original);band=tree.find('VRTRasterBand')
report=json.loads((ROOT/'national-ground-patches.json').read_text())
patches=[]
with rasterio.open(live) as base:
    for row in report['patches']:
        if row['verifiedNewSamples']<=0:continue
        source=Path(row['file'])
        target=ROOT/'tiles'/('original_patch_'+source.name)
        if target.exists() and target.read_bytes()!=source.read_bytes():raise ValueError('Immutable patch already exists with different bytes')
        if not target.exists():shutil.copyfile(source,target)
        with rasterio.open(target) as patch:
            assert patch.crs==base.crs and patch.res==base.res==(5,5)
            offset=from_bounds(*patch.bounds,transform=base.transform)
            assert all(abs(v-round(v))<1e-6 for v in (offset.col_off,offset.row_off,offset.width,offset.height))
            node=ET.Element('ComplexSource')
            ET.SubElement(node,'SourceFilename',relativeToVRT='1').text='tiles/'+target.name
            ET.SubElement(node,'SourceBand').text='1'
            ET.SubElement(node,'NODATA').text=str(patch.nodata)
            ET.SubElement(node,'SrcRect',xOff='0',yOff='0',xSize=str(patch.width),ySize=str(patch.height))
            ET.SubElement(node,'DstRect',xOff=str(round(offset.col_off)),yOff=str(round(offset.row_off)),xSize=str(patch.width),ySize=str(patch.height))
            band.insert(1,node)
            patches.append((target,offset))
staged=ROOT/'original-patch-candidate.vrt'
staged.write_bytes(ET.tostring(tree))
checks=[]
with rasterio.open(live) as before,rasterio.open(staged) as after:
    for path,window in patches:
        a=before.read(1,window=window,masked=True);b=after.read(1,window=window,masked=True)
        valid=~np.ma.getmaskarray(a)
        if not np.array_equal(a.data[valid],b.data[valid]):raise ValueError('Patch changed existing ground')
        if np.any(np.ma.getmaskarray(b)[valid]):raise ValueError('Patch removed existing ground')
        checks.append({'file':str(path),'existingCellsPreserved':int(valid.sum()),'newValidCells':int((np.ma.getmaskarray(a)&~np.ma.getmaskarray(b)).sum())})
if live.read_bytes()!=original:raise ValueError('Live mosaic changed; refusing concurrent publication')
backup=ROOT/f'ngii_dem-before-original-patch-{time.time_ns()}.vrt'
backup.write_bytes(original)
staged.replace(live)
(ROOT/'national-ground-patch-install.json').write_text(json.dumps({'at':time.time(),'installed':True,'backup':str(backup),'checks':checks},indent=2))
print(json.dumps(checks))
