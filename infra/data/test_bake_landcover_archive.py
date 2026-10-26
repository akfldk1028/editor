import io
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
from PIL import Image
import pytest

import bake_landcover_archive as m


def png(color=(207,220,192,255)):
    stream=io.BytesIO();Image.new('RGBA',(256,256),color).save(stream,format='PNG');return stream.getvalue()


def metadata():
    return {'endpoint':m.ENDPOINT,'layer':m.LAYER,'title':'test','bounds':[127,37,127.0001,37.0001],
            'updateSequence':'1','layerMetadataSHA256':'a'*64}


class Fake:
    def __init__(self):self.source=metadata();self.calls=[];self.raw=png();self.fail=False
    def metadata(self):return self.source
    def get(self,params):
        self.calls.append(params)
        if self.fail:raise RuntimeError('provider unavailable')
        return self.raw


@pytest.fixture(autouse=True)
def space(monkeypatch):
    monkeypatch.setattr(m.shutil,'disk_usage',lambda _:SimpleNamespace(free=50*1024**3))


def test_style_exact_palette_excludes_built_labels_and_strokes():
    tree=m.ET.fromstring(m.style());ns={'s':'http://www.opengis.net/sld','o':'http://www.opengis.net/ogc'}
    codes={int(n.text) for n in tree.findall('.//o:Literal',ns)}
    assert not codes.intersection({111,112,121,131,141,151,152,161,162,163})
    assert codes=={c for _,_,cs in m.GROUPS for c in cs}
    assert not tree.findall('.//s:TextSymbolizer',ns) and not tree.findall('.//s:Stroke',ns)
    assert [n.text for n in tree.findall('.//s:CssParameter',ns)]==[c for _,c,_ in m.GROUPS]


def test_metadata_bounds_and_xyz_coverage():
    raw=b'''<WMS_Capabilities xmlns="http://www.opengis.net/wms" updateSequence="5"><Capability><Layer><Layer>
      <Name>EGIS:lv3_2025y</Name><Title>cover</Title><CRS>EPSG:3857</CRS><EX_GeographicBoundingBox>
      <westBoundLongitude>125</westBoundLongitude><southBoundLatitude>33</southBoundLatitude>
      <eastBoundLongitude>132</eastBoundLongitude><northBoundLatitude>39</northBoundLatitude>
      </EX_GeographicBoundingBox></Layer></Layer></Capability></WMS_Capabilities>'''
    doc=m.source_metadata(raw);assert doc['bounds']==[125,33,132,39]
    keys=m.keys_for(doc['bounds']);assert (0,0,0) in keys and {k[0] for k in keys}==set(range(13))
    for z in range(13):
        for lon,lat in [(125.000001,33.000001),(131.999999,38.999999),(127.1,37.73)]:
            x,y=m.xy(lon,lat,z);assert (z,int(x),int(y)) in keys
    assert m.tile_bbox((0,0,0))==[-m.WORLD,-m.WORLD,m.WORLD,m.WORLD]


def test_resume_exact_hashes_no_missing_success_and_full_pack(tmp_path):
    source={**metadata(),'bounds':[127,37,127.2,37.2]}
    root,doc=m.plan(tmp_path,source);fetcher=Fake();fetcher.source=source
    result=m.fetch_tiles(root,fetcher,limit=1)
    assert result['finestReceived']==1 and result['pendingTiles']>0 and result['complete'] is False
    with pytest.raises(ValueError,match='Pending'):m.pack(root,fetcher)
    before={p.name:p.read_bytes() for p in (root/'tiles').glob('*.png')}
    result=m.fetch_tiles(root,fetcher)
    count=len(m.keys_for(source['bounds']))
    assert result['completedTiles']==count and result['pendingTiles']==0
    assert all((root/'tiles'/name).read_bytes()==raw for name,raw in before.items())
    receipt=m.pack(root,fetcher)
    assert receipt['complete'] and not receipt['published'] and receipt['tiles']==count
    assert m.pack(root,fetcher)==receipt
    raw=m.tile_paths(root,(0,0,0))[0];raw.write_bytes(png((0,0,0,0)))
    with pytest.raises(ValueError,match='receipt changed'):m.fetch_tiles(root,fetcher)


def test_premultiplied_box_ignores_hidden_rgb_and_maps_four_children():
    image=Image.new('RGBA',(256,256),(255,255,255,0))
    image.putpixel((0,0),(200,100,0,255))
    stream=io.BytesIO();image.save(stream,format='PNG')
    raw=m.parent_png([stream.getvalue(),png((0,0,255,255)),None,png((0,255,0,255))])
    with Image.open(io.BytesIO(raw)) as parent:
        red=parent.getpixel((0,0));assert red[0]>=195 and 95<=red[1]<=103 and red[2]==0 and red[3]==64
        assert parent.getpixel((200,20))==(0,0,255,255)
        assert parent.getpixel((20,200))==(0,0,0,0)
        assert parent.getpixel((200,200))==(0,255,0,255)


def test_missing_covered_child_blocks_parent_but_transparent_success_counts(tmp_path):
    root,doc=m.plan(tmp_path,metadata());keys=m.keys_for(metadata()['bounds']);keyset=set(keys)
    with pytest.raises(ValueError,match='every covered child'):m.child_evidence((0,0,0),keyset,{})
    f=Fake();f.raw=png((0,0,0,0));result=m.fetch_tiles(root,f)
    assert result['finestReceived']==1 and result['derivedParents']==12 and result['alphaEmptyTiles']==13
    assert all(float(q['bbox'].split(',')[2])-float(q['bbox'].split(',')[0])<10000 for q in f.calls)
    ready=m.verified_receipts(root,doc,keys);assert len(ready)==13
    receipt=m.tile_paths(root,(11,*[int(v) for v in m.xy(127,37,11)]))[1]
    value=json.loads(receipt.read_bytes());value['children'][0]['sha256']='bad';receipt.write_bytes(m.encoded(value))
    with pytest.raises(ValueError,match='child receipt'):m.verified_receipts(root,doc,keys)
    with pytest.raises(ValueError,match='finest'):m.params((0,0,0))


def test_pending_failure_source_change_style_pin_and_reserve_fail_closed(tmp_path,monkeypatch):
    root,doc=m.plan(tmp_path,metadata());f=Fake();f.fail=True
    result=m.fetch_tiles(root,f,limit=2)
    assert result['state']=='failed' and result['failedTiles']==1 and result['completedTiles']==0
    f.fail=False;f.source={**metadata(),'updateSequence':'2'}
    with pytest.raises(ValueError,match='source metadata changed'):m.fetch_tiles(root,f,limit=1)
    with monkeypatch.context() as patch:
        patch.setattr(m,'style',lambda:'changed')
        with pytest.raises(ValueError,match='pins changed'):m.load_plan(root)
    monkeypatch.setattr(m.shutil,'disk_usage',lambda _:SimpleNamespace(free=m.RESERVE))
    with pytest.raises(RuntimeError,match='reserve'):m.check_space(root)


def test_changed_sentinel_and_invalid_png_rejected(tmp_path):
    root,_=m.plan(tmp_path,metadata());f=Fake();m.fetch_tiles(root,f,limit=1)
    f.raw=png((1,2,3,255))
    with pytest.raises(ValueError,match='sentinel'):m.fetch_tiles(root,f,limit=1)
    for raw in [b'<ServiceException/>',b'not png']:
        with pytest.raises(ValueError,match='PNG'):m.validate_png(raw)
    stream=io.BytesIO();Image.new('RGB',(256,256)).save(stream,format='PNG')
    with pytest.raises(ValueError,match='RGBA'):m.validate_png(stream.getvalue())


def test_retry_after_bounded_and_no_retry_for_403(monkeypatch):
    calls=[];delays=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(429,headers={'retry-after':'3'}) if len(calls)==1 else httpx.Response(200,content=png())
    monkeypatch.setattr(m.time,'sleep',lambda t:delays.append(t))
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        f=m.Fetcher(client);assert f.get(m.params((12,3494,1583)))==png()
    assert len(calls)==2 and any(t>=2.9 for t in delays)
    for status,headers,error in [(403,{},httpx.HTTPStatusError),(429,{'retry-after':'3600'},ValueError)]:
        count=[]
        def bad(request):count.append(1);return httpx.Response(status,headers=headers)
        with httpx.Client(transport=httpx.MockTransport(bad)) as client:
            with pytest.raises(error):m.Fetcher(client).get({})
        assert len(count)==1


def test_sample_limit_picks_gosan_high_zoom_and_version_changes(tmp_path):
    source={**metadata(),'bounds':[125,33,132,39]};root,doc=m.plan(tmp_path,source);f=Fake();f.source=source
    result=m.fetch_tiles(root,f,limit=1,sample_point=(127.1084,37.73))
    assert result['completedTiles']==1 and result['pendingTiles']>0
    receipts=list((root/'tiles').glob('*.json'));assert json.loads(receipts[0].read_bytes())['key'][0]==12
    other,_=m.plan(tmp_path,{**source,'updateSequence':'2'});assert other!=root
