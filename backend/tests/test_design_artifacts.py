import pytest

from backend.app.modules.design.artifacts import ArtifactArchive, ArtifactArchiveError, import_artifacts


def source(tmp_path):
    root = tmp_path / 'source'
    (root / 'run1').mkdir(parents=True)
    (root / 'run1' / 'execution.json').write_bytes(b'{"status":"in_progress","path":"D:/original"}')
    (root / 'run1' / 'mass.png').write_bytes(b'original image bytes')
    (root / 'unfinished.tmp').write_bytes(b'partial preserved')
    return root


def test_preserve_bytes_retry_and_offline_read(tmp_path):
    root = source(tmp_path)
    archive = ArtifactArchive(tmp_path / 'editor')
    report = import_artifacts(archive, root, 'single-executions')
    assert report['files'] == 3 and not archive.directory.exists()
    report = import_artifacts(archive, root, 'single-executions', dry_run=False)
    assert report['added'] == 3
    assert import_artifacts(archive, root, 'single-executions', dry_run=False)['added'] == 0
    original = (root / 'run1/execution.json').read_bytes()
    root.rename(tmp_path / 'original-offline')
    entries = archive.entries('single-executions')
    assert len(entries) == 3
    assert archive.file('single-executions', 'run1/execution.json').read_bytes() == original
    assert archive.file('single-executions', 'unfinished.tmp').read_bytes() == b'partial preserved'


def test_changed_and_removed_source_cannot_replace_manifest(tmp_path):
    root = source(tmp_path); archive = ArtifactArchive(tmp_path / 'editor')
    import_artifacts(archive, root, 'single', dry_run=False)
    before = archive.entries('single')
    (root / 'run1/mass.png').write_bytes(b'changed')
    with pytest.raises(ArtifactArchiveError):
        import_artifacts(archive, root, 'single', dry_run=False)
    assert archive.entries('single') == before
    (root / 'run1/mass.png').unlink()
    with pytest.raises(ArtifactArchiveError): import_artifacts(archive, root, 'single')


def test_missing_and_tampered_blobs_fail_closed(tmp_path):
    root = source(tmp_path); archive = ArtifactArchive(tmp_path / 'editor')
    import_artifacts(archive, root, 'single', dry_run=False)
    blob = archive.file('single', 'run1/mass.png')
    blob.write_bytes(b'tampered')
    with pytest.raises(ArtifactArchiveError): archive.file('single', 'run1/mass.png')
    with pytest.raises(ArtifactArchiveError): import_artifacts(archive, root, 'single', dry_run=False)
    with pytest.raises(ArtifactArchiveError): archive.file('single', '../secret')
    with pytest.raises(ArtifactArchiveError): archive.entries('../single')


def test_nested_destination_and_symlink_rejected(tmp_path):
    root = source(tmp_path)
    with pytest.raises(ArtifactArchiveError): import_artifacts(ArtifactArchive(root / 'copy'), root, 'single')
    link = root / 'link'
    try: link.symlink_to(root / 'run1', target_is_directory=True)
    except OSError: pytest.skip('OS does not permit symlinks')
    with pytest.raises(ArtifactArchiveError): import_artifacts(ArtifactArchive(tmp_path / 'editor'), root, 'single')


def test_duplicate_content_and_additive_capture(tmp_path):
    root = source(tmp_path); archive = ArtifactArchive(tmp_path / 'editor')
    import_artifacts(archive, root, 'single', dry_run=False)
    (root / 'duplicate.png').write_bytes((root / 'run1/mass.png').read_bytes())
    report = import_artifacts(archive, root, 'single', dry_run=False)
    assert report['added'] == 1
    assert archive.file('single', 'duplicate.png') == archive.file('single', 'run1/mass.png')


def test_source_change_during_capture_keeps_previous_manifest(tmp_path, monkeypatch):
    from backend.app.modules.design import artifacts
    root = source(tmp_path); archive = ArtifactArchive(tmp_path / 'editor')
    import_artifacts(archive, root, 'single', dry_run=False)
    before = archive.entries('single')
    (root / 'new.json').write_bytes(b'new')
    original_scan = artifacts._scan
    calls = 0
    def changing_scan(path):
        nonlocal calls
        calls += 1
        if calls == 2:
            (root / 'new.json').write_bytes(b'changed while copying')
        return original_scan(path)
    monkeypatch.setattr(artifacts, '_scan', changing_scan)
    with pytest.raises(ArtifactArchiveError): import_artifacts(archive, root, 'single', dry_run=False)
    assert archive.entries('single') == before
    assert not (archive.directory / 'import.lock').exists()


def test_existing_lock_never_removed_by_other_importer(tmp_path):
    root = source(tmp_path); archive = ArtifactArchive(tmp_path / 'editor')
    import_artifacts(archive, root, 'single', dry_run=False)
    before = archive.entries('single')
    lock = archive.directory / 'import.lock';lock.write_bytes(b'active operator')
    with pytest.raises(ArtifactArchiveError): import_artifacts(archive, root, 'single', dry_run=False)
    assert lock.read_bytes() == b'active operator'
    assert archive.entries('single') == before
