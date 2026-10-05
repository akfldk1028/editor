import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image
from backend.scripts.import_portfolio_archives import plan_archive, migrate_archive


def source(tmp_path):
    root = tmp_path / 'source'
    run = root / 'original-run'
    run.mkdir(parents=True)
    Image.new('RGB', (4, 4), 'blue').save(run / 'render.png')
    record = {'candidate_id': 'one', 'program_hash': 'a' * 64, 'geometry_hash': 'b' * 64,
              'preview_path': 'render.png', 'overall_status': 'failed'}
    data = {'schema_version': 'arr.maas.portfolio_evaluation_manifest.v1', 'programs': [
        {'schema_version': 'arr.maas.portfolio_evaluation_ledger.v1', 'run_id': run.name,
         'program_slug': 'office', 'records': [record]}]}
    (run / 'maas-portfolio-evaluation.json').write_text(json.dumps(data), encoding='utf-8')
    (run / 'unrelated.bin').write_bytes(b'do not copy')
    return root


def test_exact_closure_bytes_timestamps_and_repeatability(tmp_path):
    root = source(tmp_path)
    plan = plan_archive(root, 'evaluations')
    assert len(plan['files']) == 2
    target = tmp_path / 'target'
    first = migrate_archive(root, target, 'evaluations')
    assert first == migrate_archive(root, target, 'evaluations')
    assert not (target / 'original-run/unrelated.bin').exists()
    for row in first['files']:
        a, b = root / row['path'], target / row['path']
        assert a.read_bytes() == b.read_bytes()
        assert a.stat().st_mtime_ns == b.stat().st_mtime_ns
        assert hashlib.sha256(b.read_bytes()).hexdigest() == row['sha256']
    assert first['archive_status'] == 'preserved_source_archive'


def test_conflict_fails_without_overwriting(tmp_path):
    root = source(tmp_path)
    target = tmp_path / 'target'
    (target / 'original-run').mkdir(parents=True)
    conflict = target / 'original-run/render.png'
    conflict.write_bytes(b'existing')
    with pytest.raises(FileExistsError): migrate_archive(root, target, 'evaluations')
    assert conflict.read_bytes() == b'existing'
    assert not (target / 'original-run/maas-portfolio-evaluation.json').exists()


def test_invalid_image_and_missing_source_are_rejected(tmp_path):
    root = source(tmp_path)
    (root / 'original-run/render.png').write_bytes(b'not png')
    with pytest.raises(ValueError, match='PNG'): plan_archive(root, 'evaluations')
    with pytest.raises(FileNotFoundError): plan_archive(tmp_path / 'absent', 'creative')


def test_preview_escape_is_rejected_before_copy(tmp_path):
    root = source(tmp_path)
    manifest = root / 'original-run/maas-portfolio-evaluation.json'
    data = json.loads(manifest.read_text(encoding='utf-8'))
    data['programs'][0]['records'][0]['preview_path'] = '../../outside.png'
    Image.new('RGB', (4, 4)).save(tmp_path / 'outside.png')
    manifest.write_text(json.dumps(data), encoding='utf-8')
    target = tmp_path / 'target'
    with pytest.raises(FileNotFoundError): migrate_archive(root, target, 'evaluations')
    assert not target.exists()


def test_creative_closure_keeps_referenced_mass_evidence_only(tmp_path, monkeypatch):
    root = tmp_path / 'source'
    run = root / 'creative-run'
    mass = run / 'masses/member'
    mass.mkdir(parents=True)
    for name in ('maas-creative-portfolio.json', 'candidate.json', 'masses/member/manifest.json',
                 'masses/member/handoff.json', 'masses/member/extra-evidence.json', 'unrelated.json'):
        (run / name).write_text('{}', encoding='utf-8')
    for name in ('maas-creative-board.png', 'render.png'):
        Image.new('RGB', (4, 4)).save(run / name)
    manifest = {'candidate_count': 1, 'board_png': 'maas-creative-board.png', 'candidates': [{
        'candidate_json': 'candidate.json', 'render_png': 'render.png',
        'mass_manifest': 'masses/member/manifest.json', 'elevation_research_handoff': 'masses/member/handoff.json',
        'mass_directory': 'masses/member'}]}
    monkeypatch.setattr('backend.scripts.import_portfolio_archives.validate', lambda *args: manifest)
    plan = plan_archive(root, 'creative')
    paths = {row['path'] for row in plan['files']}
    assert 'creative-run/masses/member/extra-evidence.json' in paths
    assert 'creative-run/unrelated.json' not in paths
    assert len(paths) == 7
