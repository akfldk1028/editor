import json
import sqlite3

import pytest

from backend.app.adapters.workspace.team import validate_components
from backend.app.modules.workspace.catalog import (
    NEW_TOOL_PROVIDER_PREFIX, OLD_TOOL_PROVIDER_PREFIX, CatalogRepository, migrate_tool_providers,
)
from backend.app.modules.workspace.seeds import DEFAULT_GALLERY, DEFAULT_TEAMS, LAND_TEAM_LABEL


def old_payload(payload):
    return json.dumps(payload, ensure_ascii=False).replace(NEW_TOOL_PROVIDER_PREFIX, OLD_TOOL_PROVIDER_PREFIX)


def rows(path):
    with sqlite3.connect(path) as db:
        return db.execute('SELECT id,kind,version,payload,created_at,updated_at FROM records ORDER BY id').fetchall()


def test_saved_templates_with_the_old_tool_module_are_rewritten_once(tmp_path):
    land_team = next(team for team in DEFAULT_TEAMS if team['label'] == LAND_TEAM_LABEL)
    path = tmp_path / 'catalog.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE records (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, version INTEGER NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)')
        for kind, payload in (('teams', {'component': land_team}), ('galleries', {'config': DEFAULT_GALLERY}),
                              ('teams', {'component': DEFAULT_TEAMS[0]})):
            db.execute('INSERT INTO records(kind,version,payload,created_at,updated_at) VALUES (?,3,?,?,?)',
                       (kind, old_payload(payload), 't0', 't1'))
    before = rows(path)
    stored = json.loads(before[0][3])['component']
    assert OLD_TOOL_PROVIDER_PREFIX in before[0][3] and OLD_TOOL_PROVIDER_PREFIX in before[1][3]
    with pytest.raises(ValueError):
        validate_components(stored)

    repo = CatalogRepository(tmp_path)
    after = rows(path)
    assert not any(OLD_TOOL_PROVIDER_PREFIX in row[3] for row in after)
    assert json.loads(after[0][3]) == {'component': land_team}
    assert json.loads(after[1][3]) == {'config': DEFAULT_GALLERY}
    # Only the payload changes: id, kind, version and timestamps stay as they were.
    assert [row[:3] + row[4:] for row in after] == [row[:3] + row[4:] for row in before]
    validate_components(repo.find_team(LAND_TEAM_LABEL))

    with sqlite3.connect(path) as db:
        assert migrate_tool_providers(db) == 0
    CatalogRepository(tmp_path)
    assert rows(path) == after
