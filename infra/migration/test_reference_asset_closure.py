import hashlib
from pathlib import Path
import pytest

from infra.migration.reference_asset_closure import copy_referenced_assets


def test_copy_is_bounded_byte_preserving_and_idempotent(tmp_path):
    source, destination = tmp_path / 'source', tmp_path / 'destination'
    source.mkdir()
    (source / 'image.jpg').write_bytes(b'original reference bytes')
    (source / 'unreferenced.jpg').write_bytes(b'leave behind')
    urls = ['/design/maas/reference-assets/image.jpg', 'https://example.org/image.jpg']
    receipt = copy_referenced_assets(urls, source, destination)
    assert receipt['files'][0]['sha256'] == hashlib.sha256(b'original reference bytes').hexdigest()
    assert (destination / 'image.jpg').read_bytes() == (source / 'image.jpg').read_bytes()
    assert not (destination / 'unreferenced.jpg').exists()
    assert copy_referenced_assets(urls, source, destination)['copied'] == 0


def test_collision_and_missing_sources_fail_before_copy(tmp_path):
    source, destination = tmp_path / 'source', tmp_path / 'destination'
    source.mkdir(); destination.mkdir()
    (source / 'first.jpg').write_bytes(b'first')
    (source / 'second.jpg').write_bytes(b'original')
    (destination / 'second.jpg').write_bytes(b'preserve existing')
    urls = ['/design/maas/reference-assets/' + name for name in ('first.jpg', 'second.jpg')]
    with pytest.raises(ValueError, match='conflict'):
        copy_referenced_assets(urls, source, destination)
    assert not (destination / 'first.jpg').exists()
    assert (destination / 'second.jpg').read_bytes() == b'preserve existing'
    with pytest.raises(FileNotFoundError):
        copy_referenced_assets(['/design/maas/reference-assets/absent.jpg'], source, destination)
    with pytest.raises(ValueError, match='escapes'):
        copy_referenced_assets(['/design/maas/reference-assets/../secret'], source, destination)
