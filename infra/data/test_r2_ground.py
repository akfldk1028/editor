import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from r2_ground import publish, plan, Failure
from test_r2_release import FakeS3

BASE = 'https://pub-x.r2.dev'
CUR = 'none'


class RangeS3(FakeS3):
    def get_object(self, Bucket, Key, Range=None):
        data, _ = self.objects[Key]
        if self.corrupt:
            self.corrupt -= 1; data = b'x' * len(data)
        if Range:
            start, end = map(int, Range.removeprefix('bytes=').split('-')); data = data[start:end+1]
        return {'Body': io.BytesIO(data)}


def ground(root, archive=b'pmtiles-bytes' * 1000):
    sha = hashlib.sha256(archive).hexdigest(); folder = 'a' * 64
    for kind in ('landcover-detail', 'ground-vector'):
        (root/kind/folder).mkdir(parents=True); (root/kind/folder/f'{kind.split("-")[0]}.pmtiles').write_bytes(archive)
    layer = {'kind': 'landcover', 'url': f'/api/map-data/world-ground/landcover-detail/{folder}/landcover.pmtiles', 'sha256': sha}
    vector = {'url': f'/api/map-data/world-ground/ground-vector/{folder}/ground.pmtiles', 'sha256': sha, 'level': 14}
    (root/'latest.json').write_text(json.dumps({'schema': 'world-ground/imagery-v1', 'layers': [layer], 'vector': vector}), encoding='utf8')


class GroundTests(unittest.TestCase):
    def test_uploads_archives_then_points_latest_at_absolute_r2_urls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); ground(root); client = RangeS3()
            result = publish(client=client, bucket='b', root=root, base=BASE, expected_current=CUR)
            self.assertEqual(result['archives'], 2)
            self.assertEqual(client.writes[-1], 'world-ground/latest.json')
            self.assertTrue(client.writes[-2].startswith('world-ground/releases/'))
            latest = json.loads(client.objects['world-ground/latest.json'][0])
            self.assertTrue(latest['layers'][0]['url'].startswith(BASE+'/world-ground/landcover-detail/'))
            self.assertTrue(latest['vector']['url'].startswith(BASE+'/world-ground/ground-vector/'))
            # Rerun is idempotent for archives: nothing re-uploaded.
            before = [k for k in client.writes if k.endswith('.pmtiles')]
            publish(client=client, bucket='b', root=root, base=BASE, expected_current=CUR)
            self.assertEqual([k for k in client.writes if k.endswith('.pmtiles')], before)

    def test_changed_local_archive_or_foreign_object_stops_before_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); ground(root)
            next(root.glob('landcover-detail/*/landcover.pmtiles')).write_bytes(b'changed')
            client = RangeS3()
            with self.assertRaisesRegex(Failure, 'LOCAL_ARCHIVE_CHANGED'): publish(client=client, bucket='b', root=root, base=BASE, expected_current=CUR)
            self.assertNotIn('world-ground/latest.json', client.objects)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); ground(root); client = RangeS3()
            key = plan(root)[1][0][0]; client.objects[key] = (b'other', {'Metadata': {'sha256': 'f' * 64}})
            with self.assertRaisesRegex(Failure, 'IMMUTABLE_OBJECT_COLLISION'): publish(client=client, bucket='b', root=root, base=BASE, expected_current=CUR)
            self.assertNotIn('world-ground/latest.json', client.objects)

    def test_corrupt_ranges_retry_then_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); ground(root); client = RangeS3(); client.corrupt = 1
            publish(client=client, bucket='b', root=root, base=BASE, expected_current=CUR)
            client = RangeS3(); client.corrupt = 10 ** 6
            with self.assertRaisesRegex(Failure, 'OBJECT_VERIFICATION_FAILED'): publish(client=client, bucket='b', root=root, base=BASE, expected_current=CUR)

    def test_stale_run_cannot_replace_a_newer_live_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); ground(root); client = RangeS3()
            client.objects['world-ground/latest.json'] = (b'{"newer":true}', {})
            with self.assertRaisesRegex(Failure, 'CURRENT_POINTER_CHANGED'): publish(client=client, bucket='b', root=root, base=BASE, expected_current=CUR)
            self.assertEqual(client.objects['world-ground/latest.json'][0], b'{"newer":true}')
            live = hashlib.sha256(b'{"newer":true}').hexdigest()
            self.assertEqual(publish(client=client, bucket='b', root=root, base=BASE, expected_current=live)['previous'], live)

    def test_detail_or_oversized_descriptor_is_not_publishable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); ground(root)
            d = json.loads((root/'latest.json').read_text(encoding='utf8')); d['layers'][0]['detail'] = {'urlTemplate': '/api/x/{z}/{x}/{y}.png'}
            (root/'latest.json').write_text(json.dumps(d), encoding='utf8')
            with self.assertRaisesRegex(Failure, 'NOT_PUBLISHABLE'): plan(root)

    def test_url_outside_world_ground_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); ground(root)
            d = json.loads((root/'latest.json').read_text(encoding='utf8')); d['layers'][0]['url'] = '/api/map-data/../secret.pmtiles'
            (root/'latest.json').write_text(json.dumps(d), encoding='utf8')
            with self.assertRaisesRegex(Failure, 'INVALID_GROUND_URL'): plan(root)


if __name__ == '__main__': unittest.main()
