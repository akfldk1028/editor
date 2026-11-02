import struct
import httpx
from national_delivery_probe import probe_building_delivery

REGION={'id':'r','url':'/world-buildings/r/tileset.json'}
def client(missing=False,malformed=False):
    def serve(request):
        if request.url.path.endswith('tileset.json'):
            return httpx.Response(200,json={'root':{'content':{'uri':'root.b3dm'},'children':[{'content':{'uri':'child.b3dm'}}]}})
        if missing and request.url.path.endswith('child.b3dm'):
            return httpx.Response(404)
        body=struct.pack('<4sII',b'bad!' if malformed else b'b3dm',1,28)+bytes(16)
        return httpx.Response(200,content=body,headers={'content-length':'28'})
    return httpx.Client(base_url='http://test',transport=httpx.MockTransport(serve))

def test_missing_child_is_not_success_even_when_manifest_loads():
    with client(missing=True) as c:
        row=probe_building_delivery(c,REGION)
        assert row['manifest_status']==200 and not row['valid_tileset']
        assert row['asset']=='child.b3dm'

def test_invalid_root_is_not_success():
    with client(malformed=True) as c:
        assert not probe_building_delivery(c,REGION)['valid_tileset']

def test_all_assets_and_root_header_are_checked():
    with client() as c:
        row=probe_building_delivery(c,REGION)
        assert row['valid_tileset'] and row['checked_geometry_files']==2
