import importlib.util
from pathlib import Path
import sqlite3
import pytest


def test_atomic_install_keeps_old_archive_and_moves_new_packing(tmp_path):
    import extend_terrain_details as m
    old=tmp_path/'old.pmtiles';old.write_bytes(b'old')
    packing=tmp_path/'packing.pmtiles';packing.write_bytes(b'new')
    target=tmp_path/'new.pmtiles'
    m.install_packing(packing,target,m.sha(packing),atomic_move=True)
    assert old.read_bytes()==b'old'
    assert target.read_bytes()==b'new'
    assert not packing.exists()


def test_atomic_install_rejects_collision_without_overwrite(tmp_path):
    import extend_terrain_details as m
    packing=tmp_path/'packing';packing.write_bytes(b'new')
    target=tmp_path/'existing';target.write_bytes(b'old')
    with pytest.raises(ValueError):m.install_packing(packing,target,m.sha(packing),atomic_move=True)
    assert target.read_bytes()==b'old' and packing.read_bytes()==b'new'


def test_insert_only_connection_preserves_existing_payloads(tmp_path):
    path=Path(__file__).with_name('extend_terrain_details.py')
    assert path.exists(), 'insert-only terrain detail extension is required'
    spec=importlib.util.spec_from_file_location('extension',path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    db=sqlite3.connect(tmp_path/'candidate.sqlite')
    db.execute('CREATE TABLE tiles(id INTEGER PRIMARY KEY,data BLOB)')
    db.execute('INSERT INTO tiles VALUES(1,?)',(b'preserve',))
    m.guard_existing_tiles(db)
    with pytest.raises(sqlite3.DatabaseError):db.execute('UPDATE tiles SET data=?',(b'changed',))
    with pytest.raises(sqlite3.DatabaseError):db.execute('DELETE FROM tiles')
    db.execute('INSERT INTO tiles VALUES(2,?)',(b'new',))
    assert db.execute('SELECT * FROM tiles ORDER BY id').fetchall()==[(1,b'preserve'),(2,b'new')]
