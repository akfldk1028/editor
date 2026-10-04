from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from backend.app.modules.design.artifacts import ArtifactArchive, ArtifactArchiveError, _linked
from backend.app.modules.design.execution_catalog import ExecutionCatalog, CatalogUnavailable
from backend.app.modules.design.native_repository import NativeJobRepository, NativeJobUnavailable


def remove_junction_api(path, monkeypatch):
    for cls in type(path).__mro__:
        if 'is_junction' in cls.__dict__:
            monkeypatch.delattr(cls, 'is_junction')
    assert not hasattr(path, 'is_junction')


def test_storage_opens_without_python312_junction_method(tmp_path, monkeypatch):
    remove_junction_api(tmp_path, monkeypatch)
    assert not _linked(tmp_path/'not-created')
    assert not _linked(tmp_path)
    assert ArtifactArchive(tmp_path/'archive').entries('source') == {}
    assert ExecutionCatalog(tmp_path/'catalog').list_executions() == []
    assert NativeJobRepository(tmp_path/'native').list_jobs('actor','project') == []


@pytest.mark.parametrize('mode,attributes', [
    (stat.S_IFDIR, stat.FILE_ATTRIBUTE_REPARSE_POINT),
    (stat.S_IFLNK, 0),
])
def test_junction_and_symlink_stat_evidence_rejected_without_new_path_api(tmp_path, monkeypatch, mode, attributes):
    remove_junction_api(tmp_path, monkeypatch)
    linked = tmp_path/'linked'
    original = Path.lstat
    def lstat(path, *args, **kwargs):
        if path == linked:
            return SimpleNamespace(st_mode=mode, st_file_attributes=attributes)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'lstat', lstat)
    assert _linked(linked)
    with pytest.raises(ArtifactArchiveError):ArtifactArchive(linked/'archive')
    with pytest.raises(CatalogUnavailable):ExecutionCatalog(linked/'catalog')
    with pytest.raises(NativeJobUnavailable):NativeJobRepository(linked/'native')
