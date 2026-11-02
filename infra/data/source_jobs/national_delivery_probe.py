"""Verify published geometry, not just the tileset JSON response."""
import re
import struct

def probe_building_delivery(client, region):
    url = '/api/map-data' + region['url']
    response = client.get(url)
    result = {'manifest_status': response.status_code, 'region': region['id'], 'valid_tileset': False}
    if response.status_code != 200:
        return result
    root = response.json().get('root')
    if not isinstance(root, dict):
        result['error'] = 'missing root'
        return result
    pending, uris = [root], []
    while pending:
        node = pending.pop()
        uri = node.get('content', {}).get('uri')
        if not isinstance(uri, str) or not re.fullmatch(r'[a-zA-Z0-9_-]+\.b3dm', uri):
            result['error'] = 'invalid geometry reference'
            return result
        uris.append(uri)
        children = node.get('children', [])
        if not isinstance(children, list) or not all(isinstance(child, dict) for child in children):
            result['error'] = 'invalid children'
            return result
        pending.extend(children)
        if len(uris) + len(pending) > 128:
            result['error'] = 'unexpectedly large tileset'
            return result
    prefix = url.rsplit('/', 1)[0] + '/'
    lengths = {}
    for uri in dict.fromkeys(uris):
        asset = client.head(prefix + uri)
        try:
            size = int(asset.headers.get('content-length', '0'))
        except ValueError:
            size = 0
        if asset.status_code != 200 or size < 28:
            result.update(error='missing or truncated geometry', asset=uri, asset_status=asset.status_code)
            return result
        lengths[uri] = size
    root_uri = root['content']['uri']
    with client.stream('GET', prefix + root_uri) as asset:
        header = next(asset.iter_bytes(chunk_size=28), b'')
        if asset.status_code != 200 or len(header) != 28:
            result['error'] = 'root geometry unreadable'
            return result
        magic, version, length = struct.unpack('<4sII', header[:12])
        if magic != b'b3dm' or version != 1 or length != lengths[root_uri]:
            result['error'] = 'invalid root b3dm header'
            return result
    result.update(valid_tileset=True, checked_geometry_files=len(lengths), root_header_valid=True)
    return result
