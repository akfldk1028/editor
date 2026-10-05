"""Merge Pascal histories without replacing existing rows or renumbering event IDs."""

import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

TABLES = ('scenes', 'scene_revisions', 'scene_events')
KEYS = {'scenes': ('id',), 'scene_revisions': ('scene_id', 'version'), 'scene_events': ('event_id',)}


def connect(path, writable=False):
    return sqlite3.connect(path.as_uri() + ('?mode=rw' if writable else '?mode=ro'), uri=True, timeout=10)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def snapshot(db):
    result = {}
    for table in TABLES:
        columns = [row[1] for row in db.execute(f'PRAGMA table_info({table})')]
        if not columns or not set(KEYS[table]).issubset(columns):
            raise ValueError(f'Unsupported schema: {table}')
        records = db.execute(f'SELECT * FROM {table} ORDER BY {", ".join(KEYS[table])}').fetchall()
        result[table] = {'columns': columns, 'rows': records}
    return result


def evidence(data):
    return {table: {'count': len(value['rows']), 'sha256': digest(value)} for table, value in data.items()}


def check(db):
    if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
        raise ValueError('SQLite integrity check failed')
    if db.execute('PRAGMA foreign_key_check').fetchall():
        raise ValueError('SQLite foreign key check failed')


def plan(source, destination):
    pending = {}
    for table in TABLES:
        columns = source[table]['columns']
        if columns != destination[table]['columns']:
            raise ValueError(f'Schema mismatch: {table}')
        positions = [columns.index(key) for key in KEYS[table]]
        key = lambda row: tuple(row[position] for position in positions)
        existing = {key(row): row for row in destination[table]['rows']}
        pending[table] = []
        for row in source[table]['rows']:
            if key(row) in existing:
                if row != existing[key(row)]:
                    raise ValueError(f'Record conflict in {table}: {key(row)}')
            else:
                pending[table].append(row)
    return pending


def write_receipt(directory, receipt):
    temporary = directory / 'receipt.json.tmp'
    temporary.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    temporary.replace(directory / 'receipt.json')


def merge(source, destination, output, dry_run=False):
    source, destination, output = (Path(p).resolve() for p in (source, destination, output))
    if source == destination or (source.exists() and destination.exists() and source.samefile(destination)):
        raise ValueError('Source and destination must differ')
    receipt = {'status': 'dry-run' if dry_run else 'prepared', 'created_at': datetime.now(timezone.utc).isoformat(),
               'source': str(source), 'destination': str(destination)}
    with closing(connect(source)) as src, closing(connect(destination, writable=not dry_run)) as dst:
        src.execute('BEGIN')
        dst.execute('PRAGMA foreign_keys=ON')
        dst.execute('BEGIN' if dry_run else 'BEGIN IMMEDIATE')
        try:
            check(src)
            check(dst)
            for table in TABLES:
                if src.execute(f'PRAGMA table_info({table})').fetchall() != dst.execute(f'PRAGMA table_info({table})').fetchall():
                    raise ValueError(f'Schema mismatch: {table}')
                if src.execute(f'PRAGMA foreign_key_list({table})').fetchall() != dst.execute(f'PRAGMA foreign_key_list({table})').fetchall():
                    raise ValueError(f'Foreign key schema mismatch: {table}')
                if dst.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (table,)).fetchone():
                    raise ValueError(f'Destination triggers require manual review: {table}')
            source_data, before = snapshot(src), snapshot(dst)
            pending = plan(source_data, before)
            receipt.update(source_tables=evidence(source_data), before=evidence(before),
                           inserted={table: len(rows) for table, rows in pending.items()})
            if dry_run:
                return receipt
            output.mkdir(parents=True, exist_ok=False)
            backup = output / 'destination-before.db'
            # A separate reader backs up committed WAL pages while this writer's
            # reserved lock prevents the destination changing before insertion.
            with closing(connect(destination)) as reader, closing(sqlite3.connect(backup)) as target:
                reader.backup(target)
                check(target)
                if snapshot(target) != before:
                    raise ValueError('Backup differs from the locked destination')
            receipt.update(backup=str(backup), backup_sha256=hashlib.sha256(backup.read_bytes()).hexdigest())
            write_receipt(output, receipt)
            for table, records in pending.items():
                columns = source_data[table]['columns']
                quoted = ', '.join('"' + column.replace('"', '""') + '"' for column in columns)
                dst.executemany(f'INSERT INTO {table} ({quoted}) VALUES ({", ".join("?" for _ in columns)})', records)
            check(dst)
            after = snapshot(dst)
            if any(plan(source_data, after).values()) or any(plan(before, after).values()):
                raise ValueError('Post-merge preservation verification failed')
            receipt['after'] = evidence(after)
            write_receipt(output, receipt)
            dst.commit()
            receipt['status'] = 'committed'
            write_receipt(output, receipt)
            return receipt
        except Exception as error:
            if dst.in_transaction:
                dst.rollback()
                if 'backup' in receipt:
                    receipt.update(status='rolled-back', error=str(error))
                    write_receipt(output, receipt)
            raise
        finally:
            if dst.in_transaction:
                dst.rollback()
            src.rollback()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='New private directory for backup and receipt')
    parser.add_argument('--apply', action='store_true', help='Apply transaction; default is read-only preflight')
    args = parser.parse_args()
    print(json.dumps(merge(args.source, args.destination, args.output, dry_run=not args.apply), indent=2))


if __name__ == '__main__':
    main()
