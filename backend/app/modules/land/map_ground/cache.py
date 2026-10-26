"""Only complete source responses enter the bounded, atomic display cache."""
import asyncio
import hashlib
import json
import os
import re
import time
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

from . import sources


class SourceCache:
    def __init__(self, *, transport=None):
        self.transport = transport
        self.ready = OrderedDict()
        self.pending = {}
        self.slots = asyncio.Semaphore(4)
        self.bytes = 0
        self.disk_lock = asyncio.Lock()

    def _path(self, key):
        root = Path(os.environ.get('MAP_GROUND_CACHE_DIR') or
                    Path(__file__).resolve().parents[6] / 'data/processed/map-ground')
        return root / (key + '.json')

    def _disk_read(self, key):
        try:
            path = self._path(key)
            if path.stat().st_size > 8_000_000:
                return None
            stored = json.loads(path.read_bytes())
            if stored['key'] != key or not 0 <= time.time() - stored['at'] < 600:
                return None
            payload = stored['payload']
            digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
            if digest == stored['sha256']:
                return payload
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return None

    def _disk_write(self, key, value):
        path = self._path(key)
        payload = json.dumps(value, sort_keys=True)
        stored = json.dumps({'key': key, 'at': time.time(), 'payload': value,
                             'sha256': hashlib.sha256(payload.encode()).hexdigest()})
        if len(stored) > 8_000_000:
            return
        temporary = path.with_suffix('.' + uuid.uuid4().hex + '.tmp')
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(stored, encoding='utf-8')
            temporary.replace(path)
            files = sorted((p for p in path.parent.glob('*.json') if re.fullmatch(r'[a-f0-9]{64}\.json', p.name)),
                           key=lambda p: p.stat().st_mtime, reverse=True)
            size = 0
            for i, file in enumerate(files):
                size += file.stat().st_size
                if i >= 128 or size > 64_000_000:
                    file.unlink()
        except OSError:
            pass
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    async def _produce(self, key, kind, bounds):
        try:
            value = await asyncio.to_thread(self._disk_read, key)
            if value is None:
                async with self.slots:
                    async with asyncio.timeout(45):
                        value = await sources.fetch(kind, bounds, os.environ.get('VWORLD_API_KEY', ''),
                                                    transport=self.transport)
                value['record']['retrieved'] = datetime.now(timezone.utc).isoformat()
                value['record']['revision'] = await asyncio.to_thread(
                    lambda: hashlib.sha256(json.dumps(value['rows'], sort_keys=True).encode()).hexdigest())
                async with self.disk_lock:
                    await asyncio.to_thread(self._disk_write, key, value)
            size = await asyncio.to_thread(lambda: len(json.dumps(value)))
            if size <= 8_000_000:
                age = max(0, time.time() - datetime.fromisoformat(value['record']['retrieved']).timestamp())
                self.ready[key] = (time.monotonic() - age, value, size)
                self.bytes += size
                while len(self.ready) > 64 or self.bytes > 32_000_000:
                    self.bytes -= self.ready.popitem(last=False)[1][2]
            return value
        except TimeoutError:
            raise sources.SourceUnavailable(f'{kind}: viewport request timed out') from None
        finally:
            self.pending.pop(key, None)

    async def get(self, kind, bounds):
        key = hashlib.sha256(json.dumps(['map-ground-v1', sources.LAYERS[kind], bounds]).encode()).hexdigest()
        hit = self.ready.get(key)
        if hit:
            if time.monotonic() - hit[0] < 600:
                self.ready.move_to_end(key)
                return hit[1]
            self.bytes -= self.ready.pop(key)[2]
        if key not in self.pending:
            if len(self.pending) >= 16:
                raise sources.SourceUnavailable(f'{kind}: display busy; retry viewport')
            task = asyncio.create_task(self._produce(key, kind, bounds))
            self.pending[key] = task
            task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
        return await asyncio.shield(self.pending[key])
