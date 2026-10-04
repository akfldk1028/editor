import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


TOOL = Path(__file__).parents[1] / 'inventory.py'


@pytest.fixture(autouse=True)
def isolated_git_configuration(monkeypatch):
    monkeypatch.setenv('GIT_CONFIG_NOSYSTEM', '1')
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', os.devnull)


def load():
    spec = importlib.util.spec_from_file_location('migration_inventory', TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args])


def test_dirty_git_inventory_and_restored_bytes(tmp_path):
    source = tmp_path / 'source spaces 한글'
    source.mkdir()
    git(source, 'init', '-q')
    (source / '.gitignore').write_text('ignored.txt\n')
    (source / 'tracked.txt').write_text('committed')
    git(source, 'add', '.')
    git(source, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture')
    (source / 'tracked.txt').write_text('dirty')
    (source / '새 파일.txt').write_text('untracked')
    (source / 'ignored.txt').write_text('ignored')
    tool = load()
    manifest = tool.scan(source)
    assert manifest['complete'] is True
    repo = manifest['repositories'][0]
    assert repo['commit'] == git(source, 'rev-parse', 'HEAD').decode().strip()
    assert 'tracked.txt' in [entry['path'] for entry in repo['index']]
    assert '새 파일.txt' in repo['untracked']
    assert 'ignored.txt' in repo['ignored']
    assert any(item['path'] == 'tracked.txt' for item in repo['status'])
    assert all('sha256' in item for item in manifest['entries'] if item['kind'] == 'file')
    restored = tmp_path / 'restored'
    shutil.copytree(source, restored)
    assert tool.verify(manifest, restored)['verified'] is True
    (restored / 'tracked.txt').write_text('other')
    (restored / '새 파일.txt').unlink()
    (restored / 'extra.txt').write_text('new')
    result = tool.verify(manifest, restored)
    assert result['verified'] is False
    assert 'tracked.txt' in result['changed']
    assert '새 파일.txt' in result['missing']
    assert 'extra.txt' in result['extra']


def test_link_escape_is_recorded_not_followed(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'secret.txt').write_text('never enumerate')
    try:
        (source / 'escape').symlink_to(outside, target_is_directory=True)
    except OSError:
        if os.name != 'nt':
            pytest.skip('symlinks unavailable')
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(source / 'escape'), str(outside)], check=True, capture_output=True)
    manifest = load().scan(source)
    assert [entry['path'] for entry in manifest['entries']] == ['escape']
    assert manifest['entries'][0]['kind'] == 'link'
    assert manifest['entries'][0]['target']


def test_metadata_is_not_backup_evidence_and_output_must_be_external(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'a').write_bytes(b'abc')
    tool = load()
    assert tool.verify(tool.scan(source, metadata_only=True), source)['verified'] is False
    process = subprocess.run([sys.executable, str(TOOL), 'scan', '--source', str(source), '--output', str(source / 'manifest.json')], capture_output=True)
    assert process.returncode != 0
    assert not (source / 'manifest.json').exists()


def test_hash_read_failure_and_changed_during_hash_are_explicit(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    source.mkdir()
    target = source / 'a'
    target.write_bytes(b'abc')
    tool = load()
    original = tool.hash_file
    def mutate(path, before):
        result = original(path, before)
        path.write_bytes(b'changed while scanning')
        return result
    monkeypatch.setattr(tool, 'hash_file', mutate)
    manifest = tool.scan(source)
    assert not manifest['complete']
    assert any(error['code'] == 'file_changed_during_hash' for error in manifest['errors'])
    def denied(*_):
        raise PermissionError('denied fixture')
    monkeypatch.setattr(tool, 'hash_file', denied)
    manifest = tool.scan(source)
    assert not manifest['complete'] and manifest['errors']


@pytest.mark.skipif(os.name != 'nt', reason='Windows directory stat-size semantics')
def test_directory_allocation_size_is_not_content_change_but_mtime_is(tmp_path, monkeypatch):
    from types import SimpleNamespace
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'child.txt').write_bytes(b'preserved')
    actual_lstat = Path.lstat
    counter = {'value': 0}
    alter_mtime = {'value': False}
    def unstable_directory_info(path, *args, **kwargs):
        actual = actual_lstat(path, *args, **kwargs)
        if path != source:
            return actual
        counter['value'] += 1
        values = {key: getattr(actual, key) for key in dir(actual) if key.startswith('st_')}
        values['st_size'] = 65536 if counter['value'] % 2 else 0
        if alter_mtime['value'] and counter['value'] % 2:
            values['st_mtime_ns'] += 1
        return SimpleNamespace(**values)
    monkeypatch.setattr(Path, 'lstat', unstable_directory_info)
    tool = load()
    manifest = tool.scan(source)
    assert manifest['complete'], manifest['errors']
    alter_mtime['value'] = True
    assert not tool.scan(source)['complete']


def test_raw_reparse_metadata_is_compared_and_required_for_unknown_target(tmp_path, monkeypatch):
    from hashlib import sha256
    from base64 import b64encode
    tool = load()
    raw = b'raw-reparse-fixture'
    entry = {'path': 'linux-python', 'kind': 'link', 'target': None,
             'reparse_tag': 2684354589, 'reparse_data_base64': b64encode(raw).decode(),
             'reparse_data_sha256': sha256(raw).hexdigest(), 'readlink_error': 'unsupported'}
    manifest = {'schema_version': tool.SCHEMA, 'complete': True, 'mode': 'sha256',
                'errors': [], 'entries': [entry]}
    monkeypatch.setattr(tool, 'scan', lambda *_: manifest)
    assert tool.verify(manifest, tmp_path)['verified']
    changed = {**entry, 'reparse_data_sha256': '0' * 64}
    monkeypatch.setattr(tool, 'scan', lambda *_: {**manifest, 'entries': [changed]})
    assert tool.verify(manifest, tmp_path)['changed'] == ['linux-python']
    invalid = {**entry, 'reparse_data_base64': ''}
    assert not tool.verify({**manifest, 'entries': [invalid]}, tmp_path)['verified']


def test_case_collision_and_invalid_manifest(tmp_path):
    tool = load()
    assert tool.case_collisions(['A/file', 'a/file'])
    assert not tool.verify({'schema_version': 'wrong'}, tmp_path)['verified']


def test_nested_repository_unborn_branch_and_external_git_pointer(tmp_path):
    source = tmp_path / 'source'
    nested = source / 'nested'
    nested.mkdir(parents=True)
    git(nested, 'init', '-q')
    tool = load()
    manifest = tool.scan(source)
    assert manifest['complete']
    assert manifest['repositories'][0]['path'] == 'nested'
    assert manifest['repositories'][0]['commit'] is None
    worktree = source / 'worktree'
    worktree.mkdir()
    (worktree / '.git').write_text('gitdir: ../../outside/private')
    manifest = tool.scan(source)
    assert not manifest['complete']
    assert any(error['path'] == 'worktree' and error['code'] == 'external_git_pointer_not_inspected' for error in manifest['errors'])


def test_source_inside_parent_repository_is_scoped(tmp_path):
    parent = tmp_path / 'parent'
    source = parent / 'AG frontend'
    source.mkdir(parents=True)
    git(parent, 'init', '-q')
    (parent / '.gitignore').write_text('*.ignored\n')
    (parent / 'outside.txt').write_text('outside')
    (source / 'inside.txt').write_text('inside')
    git(parent, 'add', '.')
    git(parent, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture')
    for folder in (parent, source):
        (folder / 'new.txt').write_text('new')
        (folder / 'private.ignored').write_text('ignored')
    (parent / 'outside.txt').write_text('dirty outside')
    (source / 'inside.txt').write_text('dirty inside')
    manifest = load().scan(source)
    assert manifest['complete']
    assert manifest['resolved_root'] == str(source.resolve())
    assert len(manifest['repositories']) == 1
    repo = manifest['repositories'][0]
    assert Path(repo['git_root']) == parent.resolve()
    assert repo['source_subpath'] == 'AG frontend/'
    assert [item['path'] for item in repo['index']] == ['inside.txt']
    assert repo['untracked'] == ['new.txt']
    assert repo['ignored'] == ['private.ignored']
    assert {item['path'] for item in repo['status']} == {'inside.txt', 'new.txt'}


@pytest.mark.parametrize('filter_command', ['clean', 'process'])
def test_configured_clean_filter_is_never_executed(tmp_path, filter_command):
    source = tmp_path / 'filtered'
    source.mkdir()
    git(source, 'init', '-q')
    (source / 'tracked.txt').write_text('original')
    git(source, 'add', '.')
    git(source, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture')
    marker = tmp_path / 'filter-was-executed'
    script = tmp_path / 'dangerous-filter.py'
    script.write_text('import sys\nfrom pathlib import Path\nPath(sys.argv[1]).write_text("unsafe")\nsys.stdout.write(sys.stdin.read())\n')
    command = f'"{Path(sys.executable).as_posix()}" "{script.as_posix()}" "{marker.as_posix()}"'
    git(source, 'config', f'filter.fixture.{filter_command}', command)
    (source / '.gitattributes').write_text('*.txt filter=fixture\n')
    (source / 'tracked.txt').write_text('modified')
    manifest = load().scan(source)
    assert not marker.exists(), 'inventory executed a configured external clean filter'
    repo = manifest['repositories'][0]
    assert repo['status'] is None
    assert repo['status_inspected'] is False
    assert repo['status_skip_reason'] == 'configured_external_filters'
    assert repo['external_filter_keys'] == [f'filter.fixture.{filter_command}']
    assert not manifest['complete']
    assert manifest['filesystem_complete'] is True
    assert manifest['git_state_complete'] is False
    assert manifest['errors']


def test_configured_but_unused_filter_does_not_block_git_inventory(tmp_path):
    source = tmp_path / 'unused-filter'
    source.mkdir()
    git(source, 'init', '-q')
    (source / 'tracked.txt').write_text('file')
    git(source, 'add', '.')
    git(source, 'config', 'filter.unused.clean', 'must-never-execute-fixture')
    manifest = load().scan(source)
    assert manifest['complete']
    assert manifest['filesystem_complete'] and manifest['git_state_complete']
    repo = manifest['repositories'][0]
    assert repo['status_inspected']
    assert repo['active_filter_keys'] == []
    assert repo['external_filter_keys'] == ['filter.unused.clean']


def test_incomplete_scan_cli_exits_nonzero_and_keeps_error_manifest(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / '.git').write_text('gitdir: ../outside')
    output = tmp_path / 'incomplete.json'
    process = subprocess.run([sys.executable, str(TOOL), 'scan', '--source', str(source), '--output', str(output)], capture_output=True)
    assert process.returncode == 1
    manifest = json.loads(output.read_text(encoding='utf-8'))
    assert manifest['errors'] and not manifest['complete']
    assert not load().verify(manifest, source)['verified']


@pytest.mark.skipif(os.name != 'nt', reason='Windows entrypoint')
def test_powershell_wrapper_handles_spaces_and_metadata_mode(tmp_path):
    source = tmp_path / 'source spaces'
    source.mkdir()
    (source / 'file.txt').write_text('data')
    output = tmp_path / 'manifest spaces.json'
    result = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                             str(TOOL.parent / 'inventory.ps1'), '-Source', str(source),
                             '-Output', str(output), '-Python', sys.executable, '-MetadataOnly'], capture_output=True)
    assert result.returncode == 0, result.stderr
    manifest = json.loads(output.read_text(encoding='utf-8'))
    assert manifest['mode'] == 'metadata_only'
    assert not load().verify(manifest, source)['verified']


def test_cli_manifest_and_verify_entrypoint(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / '한 글.txt').write_bytes(b'fixture')
    manifest = tmp_path / 'manifest.json'
    subprocess.run([sys.executable, str(TOOL), 'scan', '--source', str(source), '--output', str(manifest)], check=True, capture_output=True)
    assert json.loads(manifest.read_text(encoding='utf-8'))['complete']
    result = subprocess.run([sys.executable, str(TOOL.parent / 'verify-manifest.py'), '--manifest', str(manifest), '--root', str(source)], capture_output=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['verified']
