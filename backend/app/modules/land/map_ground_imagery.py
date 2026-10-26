"""Bounded, mutable-provider detail tiles; never writes a publication pointer."""
import asyncio
from email.utils import parsedate_to_datetime
import hashlib
import io
import json
import math
import os
from pathlib import Path
import time
import uuid

import httpx
from PIL import Image

ENDPOINT = 'https://api.mcee.go.kr/geoserver/wms'
LAYER = 'EGIS:lv3_2025y'
STYLE_SHA = '291c7488d4e43750477445b3646027e69eb3b1bc3888072d16cc369af833fd72'
BOUNDS = (125.0749972065207, 33.09999943194731, 131.87500136217878, 38.37500335369369)
LIMIT = 1024 * 1024
TTL = 86400
VERSION = hashlib.sha256(json.dumps([ENDPOINT, LAYER, BOUNDS, STYLE_SHA, 'rgba256-detail-v1']).encode()).hexdigest()


class ImageryUnavailable(RuntimeError):
    pass


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def validate_png(raw):
    if (len(raw) > LIMIT or len(raw) < 29 or raw[:8] != b'\x89PNG\r\n\x1a\n'
            or raw[8:16] != b'\x00\x00\x00\x0dIHDR' or raw[16:24] != b'\x00\x00\x01\x00'*2
            or raw[24:26] != b'\x08\x06'):
        raise ImageryUnavailable('Invalid ground imagery response')
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.size != (256, 256) or image.mode != 'RGBA' or image.format != 'PNG':
                raise ValueError()
            image.verify()
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            return image.getchannel('A').getbbox() is None
    except (OSError, ValueError, SyntaxError):
        raise ImageryUnavailable('Invalid ground imagery response') from None


def transparent():
    output = io.BytesIO()
    Image.new('RGBA', (256, 256)).save(output, format='PNG')
    return output.getvalue()


EMPTY = transparent()


class GroundImagery:
    def __init__(self, *, root=None, transport=None, interval=1.0):
        data = Path(os.environ.get('DATA_ROOT') or Path(__file__).resolve().parents[4] / 'data')
        self.root = Path(root) if root is not None else data / 'cache/world-ground' / VERSION
        self.transport = transport
        self.interval = interval
        self.pending = {}
        self.slots = asyncio.Semaphore(2)
        self.rate = asyncio.Lock()
        self.last_request = float('-inf')
        raw = (Path(__file__).parent / 'resources/egis-lv3-2025-diagram.sld').read_bytes()
        if digest(raw) != STYLE_SHA:
            raise ValueError('Ground imagery style fingerprint changed')
        self.style = raw.decode('utf-8')

    def paths(self, key):
        z, x, y = key
        path = self.root / str(z) / str(x) / f'{y}.png'
        return path, path.with_suffix('.json')

    def cached(self, key):
        png, receipt = self.paths(key)
        try:
            if png.is_symlink() or receipt.is_symlink() or png.stat().st_size > LIMIT or receipt.stat().st_size > 4096:
                return None
            record = json.loads(receipt.read_bytes())
            if record['version'] != VERSION or record['key'] != list(key) or not 0 <= time.time() - record['at'] < TTL:
                return None
            raw = png.read_bytes()
            if record['sha256'] == digest(raw) and record['bytes'] == len(raw) and validate_png(raw) == record['alphaEmpty']:
                return raw
        except (OSError, ValueError, KeyError, TypeError, ImageryUnavailable):
            pass
        return None

    def store(self, key, raw, empty):
        png, receipt = self.paths(key)
        png.parent.mkdir(parents=True, exist_ok=True)
        record = {'version': VERSION, 'key': key, 'at': time.time(), 'bytes': len(raw),
                  'sha256': digest(raw), 'styleSHA256': STYLE_SHA, 'layer': LAYER, 'alphaEmpty': empty}
        for path, content in ((png, raw), (receipt, json.dumps(record).encode())):
            temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
            try:
                temporary.write_bytes(content)
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)

    async def get(self, z, x, y):
        if not 13 <= z <= 17 or not 0 <= x < 2**z or not 0 <= y < 2**z:
            raise ValueError('Invalid ground imagery tile coordinates')
        n = 2**z
        lat = lambda row: math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * row / n))))
        if x/n*360-180 >= BOUNDS[2] or (x+1)/n*360-180 <= BOUNDS[0] or lat(y) <= BOUNDS[1] or lat(y+1) >= BOUNDS[3]:
            return EMPTY
        key = z, x, y
        if key not in self.pending:
            if len(self.pending) >= 64:
                raise ImageryUnavailable('Ground imagery busy')
            task = asyncio.create_task(self.load(key))
            self.pending[key] = task
            task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
        # One disconnected browser cannot cancel another consumer of this tile.
        return await asyncio.shield(self.pending[key])

    async def load(self, key):
        try:
            async with self.slots:
                cached = await asyncio.to_thread(self.cached, key)
                if cached is not None:
                    return cached
                async with asyncio.timeout(55):
                    raw = await self.fetch(key)
                empty = validate_png(raw)
                await asyncio.to_thread(self.store, key, raw, empty)
                return raw
        except (OSError, TimeoutError, httpx.HTTPError):
            raise ImageryUnavailable('Ground imagery unavailable') from None
        finally:
            self.pending.pop(key, None)

    async def fetch(self, key):
        z, x, y = key
        world = 20037508.342789244
        span = 2 * world / 2**z
        params = {'SERVICE': 'WMS', 'REQUEST': 'GetMap', 'VERSION': '1.3.0', 'CRS': 'EPSG:3857',
                  'LAYERS': LAYER, 'STYLES': '', 'FORMAT': 'image/png', 'TRANSPARENT': 'true',
                  'WIDTH': 256, 'HEIGHT': 256, 'SLD_BODY': self.style,
                  'BBOX': ','.join(map(str, (x*span-world, world-(y+1)*span, (x+1)*span-world, world-y*span)))}
        async with httpx.AsyncClient(transport=self.transport, timeout=httpx.Timeout(15, connect=5),
                                     follow_redirects=False, trust_env=False) as client:
            for attempt in range(3):
                async with self.rate:
                    await asyncio.sleep(max(0, self.interval - (time.monotonic() - self.last_request)))
                    self.last_request = time.monotonic()
                delay = 2**attempt
                try:
                    async with client.stream('GET', ENDPOINT, params=params) as response:
                        if response.status_code in (429, 502, 503, 504):
                            retry = response.headers.get('Retry-After', '')
                            try:
                                seconds = float(retry) if retry.isdigit() else max(0, parsedate_to_datetime(retry).timestamp()-time.time())
                            except (ValueError, TypeError, OverflowError):
                                seconds = 0
                            if seconds:
                                if seconds > 8:
                                    raise ImageryUnavailable('Ground imagery temporarily unavailable')
                                delay = max(delay, seconds)
                        elif response.status_code != 200:
                            raise ImageryUnavailable('Ground imagery unavailable')
                        else:
                            length = response.headers.get('Content-Length')
                            if length and (not length.isdigit() or int(length) > LIMIT):
                                raise ImageryUnavailable('Invalid ground imagery response')
                            body = bytearray()
                            async for chunk in response.aiter_bytes():
                                if len(body) + len(chunk) > LIMIT:
                                    raise ImageryUnavailable('Invalid ground imagery response')
                                body.extend(chunk)
                            return bytes(body)
                except (httpx.TimeoutException, httpx.NetworkError):
                    pass
                if attempt < 2:
                    await asyncio.sleep(delay)
            raise ImageryUnavailable('Ground imagery temporarily unavailable')
