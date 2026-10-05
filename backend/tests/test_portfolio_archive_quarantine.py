import json
from pathlib import Path

import pytest
from PIL import Image
from backend.scripts.quarantine_portfolio_archives import plan_quarantine, quarantine_archives
from backend.app.modules.design.generation.maas.creative_portfolio_catalog import creative_portfolio_manifest


def failed_source(tmp_path):
    root = tmp_path / 'source'
    run = root / 'failed-run'
    mass = run / 'masses/member'
    mass.mkdir(parents=True)
    row = {'candidate_json': 'candidate.json', 'render_png': 'render.png', 'mass_directory': 'masses/member',
           'mass_manifest': 'masses/member/manifest.json', 'elevation_research_handoff': 'masses/member/handoff.json'}
    data = {'run_id': 'original-identity-mismatch', 'candidates': [row], 'candidate_count': 1}
    (run / 'maas-creative-portfolio.json').write_text(json.dumps(data), encoding='utf-8')
    for name in ('candidate.json', 'masses/member/manifest.json', 'masses/member/handoff.json'):
        (run / name).write_text('{}', encoding='utf-8')
    for name in ('maas-creative-board.png', 'render.png'):
        Image.new('RGB', (4, 4)).save(run / name)
    return root


def test_quarantine_preserves_failure_and_bytes_without_active_promotion(tmp_path):
    source = failed_source(tmp_path)
    destination = tmp_path / 'archive-quarantine/creative-portfolios'
    result = quarantine_archives(source, destination, ['failed-run'])
    assert result == quarantine_archives(source, destination, ['failed-run'])
    assert result['archive_status'] == 'quarantined_validation_failure'
    assert result['active_catalog_eligible'] is False
    assert result['validation_failures'][0]['reason'] == 'creative portfolio run ID mismatch'
    assert result['validation_failures'][0]['error_type'] == 'ValueError'
    assert result['validation_failures'][0]['source_manifest_sha256']
    for row in result['files']:
        assert (source / row['path']).read_bytes() == (destination / row['path']).read_bytes()
    with pytest.raises(ValueError, match='run ID mismatch'):
        creative_portfolio_manifest(destination, 'failed-run')
    assert not (tmp_path / 'creative-portfolios').exists()


def test_active_destination_and_conflicts_are_rejected(tmp_path):
    source = failed_source(tmp_path)
    with pytest.raises(ValueError, match='archive-quarantine'):
        quarantine_archives(source, tmp_path / 'creative-portfolios', ['failed-run'])
    target = tmp_path / 'archive-quarantine/creative-portfolios'
    (target / 'failed-run').mkdir(parents=True)
    (target / 'failed-run/render.png').write_bytes(b'existing')
    with pytest.raises(FileExistsError): quarantine_archives(source, target, ['failed-run'])
    assert (target / 'failed-run/render.png').read_bytes() == b'existing'


def test_quarantine_rejects_escaping_references(tmp_path):
    source = failed_source(tmp_path)
    path = source / 'failed-run/maas-creative-portfolio.json'
    value = json.loads(path.read_text())
    value['candidates'][0]['mass_directory'] = '../../outside'
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='MASS directory'): plan_quarantine(source, ['failed-run'])


def test_successful_catalog_cannot_be_quarantined(tmp_path, monkeypatch):
    source = failed_source(tmp_path)
    monkeypatch.setattr('backend.scripts.quarantine_portfolio_archives.validate', lambda *args: {})
    with pytest.raises(ValueError, match='not eligible'):
        plan_quarantine(source, ['failed-run'])


def test_corrupt_image_is_preserved_with_failure_evidence(tmp_path):
    source = failed_source(tmp_path)
    original = source / 'failed-run/render.png'
    original.write_bytes(b'original damaged image')
    target = tmp_path / 'archive-quarantine/creative-portfolios'
    receipt = quarantine_archives(source, target, ['failed-run'])
    assert receipt['image_failures'][0]['path'] == 'failed-run/render.png'
    assert (target / 'failed-run/render.png').read_bytes() == original.read_bytes()
    assert receipt['active_catalog_eligible'] is False
