from contextlib import closing, contextmanager
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sqlite3
from uuid import uuid4
from .pnu import normalize_pnu


class LandRepository:
    def __init__(self, directory: Path | str):
        root = Path(directory)
        if not root.is_absolute():
            raise ValueError('land data directory must be absolute')
        self.path = root / 'land.sqlite'

    @contextmanager
    def _transaction(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.row_factory = sqlite3.Row
            db.execute('BEGIN IMMEDIATE')
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1, 2):
                raise ValueError('unsupported land database version')
            if version == 0:
                db.execute('''CREATE TABLE analyses (
                    analysis_id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
                    input_type TEXT NOT NULL, request_json TEXT NOT NULL,
                    result_json TEXT NOT NULL, elapsed_ms REAL NOT NULL,
                    error TEXT NOT NULL)''')
            if version < 2:
                db.execute('''CREATE TABLE land_cache (
                    pnu TEXT PRIMARY KEY, fetched_at TEXT NOT NULL, result_json TEXT NOT NULL)''')
                db.execute('''CREATE TABLE IF NOT EXISTS zone_cache (
                    cache_key TEXT PRIMARY KEY, fetched_at TEXT NOT NULL, features_json TEXT NOT NULL)''')
                db.execute('PRAGMA user_version=2')
            yield db

    def save(self, request: dict, result: dict, elapsed_ms: float, error: str = '') -> str:
        if not isinstance(request, dict) or not isinstance(result, dict):
            raise ValueError('analysis request and result must be objects')
        if type(elapsed_ms) not in (int, float) or not math.isfinite(elapsed_ms) or elapsed_ms < 0:
            raise ValueError('elapsed_ms must be finite and nonnegative')
        input_type = request.get('input_type', 'pnu')
        if not isinstance(input_type, str) or not isinstance(error, str):
            raise ValueError('input_type and error must be strings')
        request_json = json.dumps(request, ensure_ascii=False, allow_nan=False)
        result_json = json.dumps(result, ensure_ascii=False, allow_nan=False)
        analysis_id = str(uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        with self._transaction() as db:
            db.execute('INSERT INTO analyses VALUES (?, ?, ?, ?, ?, ?, ?)',
                       (analysis_id, created_at, input_type, request_json, result_json, elapsed_ms, error))
        return analysis_id

    def get(self, analysis_id: str) -> dict | None:
        with self._transaction() as db:
            row = db.execute('SELECT * FROM analyses WHERE analysis_id=?', (analysis_id,)).fetchone()
        if row is None:
            return None
        return {'analysis_id': row['analysis_id'], 'created_at': row['created_at'],
                'request': json.loads(row['request_json']), 'result': json.loads(row['result_json']),
                'elapsed_ms': row['elapsed_ms'], 'error': row['error']}

    def stats(self) -> dict:
        with self._transaction() as db:
            totals = db.execute('''SELECT COUNT(*) AS total, AVG(elapsed_ms) AS average,
                                  SUM(CASE WHEN error <> '' THEN 1 ELSE 0 END) AS errors
                                  FROM analyses''').fetchone()
            groups = db.execute('''SELECT input_type, COUNT(*) AS count FROM analyses
                                   GROUP BY input_type ORDER BY count DESC, input_type ASC''').fetchall()
        return {'total_queries': totals['total'], 'avg_response_time_ms': round(totals['average'] or 0, 2),
                'error_count': totals['errors'] or 0,
                'by_input_type': [{'input_type': row['input_type'], 'count': row['count']} for row in groups]}

    @staticmethod
    def _validate_land_cache(pnu, result):
        if normalize_pnu(pnu) != pnu or not isinstance(result, dict):
            raise ValueError('Invalid land cache identity')
        if result.get('pnu') != pnu or result.get('success') is not True or result.get('source') != 'vworld':
            raise ValueError('Only successful provider data can be cached')
        zones = result.get('zones')
        if not isinstance(zones, list) or not zones or not all(isinstance(z, str) and z.strip() for z in zones):
            raise ValueError('Cache requires resolved zones')
        for key in ('land_area_m2', 'official_land_price'):
            value = result.get(key)
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
                raise ValueError('Invalid land cache numeric value')
        if not isinstance(result.get('land_use_situation'), str):
            raise ValueError('Invalid land use situation')

    def put_land_cache(self, pnu: str, result: dict) -> None:
        self._validate_land_cache(pnu, result)
        value = json.dumps(result, ensure_ascii=False, allow_nan=False)
        timestamp = datetime.now(timezone.utc).isoformat()
        with self._transaction() as db:
            db.execute('INSERT INTO land_cache VALUES (?, ?, ?) ON CONFLICT(pnu) DO UPDATE SET '
                       'fetched_at=excluded.fetched_at, result_json=excluded.result_json', (pnu, timestamp, value))

    def get_land_cache(self, pnu: str) -> dict | None:
        pnu = normalize_pnu(pnu)
        with self._transaction() as db:
            row = db.execute('SELECT * FROM land_cache WHERE pnu=?', (pnu,)).fetchone()
        if row is None:
            return None
        result = json.loads(row['result_json'])
        self._validate_land_cache(pnu, result)
        if datetime.fromisoformat(row['fetched_at']).tzinfo is None:
            raise ValueError('Cache timestamp has no timezone')
        return {'result': result, 'fetched_at': row['fetched_at']}

    def put_zone_cache(self, cache_key: str, features: list) -> None:
        if not features or not all(isinstance(feature, dict) for feature in features):
            raise ValueError('Zone cache requires features')
        data = json.dumps(features, ensure_ascii=False, allow_nan=False)
        with self._transaction() as db:
            db.execute('INSERT INTO zone_cache VALUES (?, ?, ?) ON CONFLICT(cache_key) DO UPDATE SET '
                       'fetched_at=excluded.fetched_at, features_json=excluded.features_json',
                       (cache_key, datetime.now(timezone.utc).isoformat(), data))

    def get_zone_cache(self, cache_key: str) -> dict | None:
        with self._transaction() as db:
            row = db.execute('SELECT * FROM zone_cache WHERE cache_key=?', (cache_key,)).fetchone()
        if row is None:
            return None
        features = json.loads(row['features_json'])
        if not isinstance(features, list) or not features or not all(isinstance(f, dict) for f in features):
            raise ValueError('Invalid zone cache')
        if datetime.fromisoformat(row['fetched_at']).tzinfo is None:
            raise ValueError('Cache timestamp has no timezone')
        return {'features': features, 'fetched_at': row['fetched_at']}
