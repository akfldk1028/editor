import { mkdtempSync, statSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { Database } from 'bun:sqlite'
import { expect, test } from 'bun:test'
import { deflateSync } from 'node:zlib'
import { canonicalRegions, openCanonicalSnapshot } from './ngii-canonical-source'

const hash = 'a'.repeat(64), source = 'b'.repeat(64)
const manifest = { family: 'NGII-B021', productCode: 'B021', productKind: 'continuous-topographic',
  layer: 'N3A_B0010000', crs: 'EPSG:5179', edition: '2024', file: 'buildings.zip',
  sourceManifestSHA256: 'c'.repeat(64), productReceiptSHA256: 'd'.repeat(64) }
const ring = [[127,37],[127.0001,37],[127.0001,37.0001],[127,37]]
const row = { canonicalBuildingId: `ngii:${'e'.repeat(64)}`, sourceUFID: 'example',
  anchorWGS84: [127,37], h: 3.4, heightSource: { kind: 'declared-default' },
  geomWGS84: { type: 'MultiPolygon', coordinates: [[ring],[ring]] }, provenance: { sourceId: source, row: 0 } }
const plan = { schema: 'ngii-canonical-plan-v1', storageSchema: 'canonical-sqlite-v2', planSHA256: hash,
  expectedRows: 1, sources: [{ id: source, expectedRows: 1, manifest }] }
const inventory = { schema: 'ngii-canonical-regions-v1', planSHA256: hash, sourceComplete: true,
  sourceRows: 1, buildingCount: 1, regionCount: 1, regions: [{ region14: '14/13971/6377', buildings: 1, components: 2 }] }

function fixture(complete = true) {
  const db = new Database(':memory:')
  db.exec('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT); CREATE TABLE sources(id TEXT,expected_rows INTEGER,next_row INTEGER,status TEXT,manifest TEXT); CREATE TABLE issues(kind TEXT); CREATE TABLE buildings(id TEXT,region14 TEXT,region16 TEXT,payload BLOB)')
  db.query('INSERT INTO metadata VALUES(?,?)').run('planSHA256', hash)
  db.query('INSERT INTO sources VALUES(?,?,?,?,?)').run(source, 1, Number(complete), complete ? 'complete' : 'partial', JSON.stringify(manifest))
  db.query('INSERT INTO buildings VALUES(?,?,?,?)').run(row.canonicalBuildingId, inventory.regions[0]!.region14, '16/55885/25508', deflateSync(JSON.stringify(row)))
  return db
}

test('completed canonical regions stream zlib payload with original source provenance', () => {
  const db = fixture(), snapshot = canonicalRegions(db, plan, inventory)
  try {
    expect([...snapshot.rows(inventory.regions[0]!.region14)]).toEqual([{ ...row, provenance: { ...manifest, row: 0 } }])
    expect(snapshot.regions).toEqual(inventory.regions)
    expect(() => db.exec("INSERT INTO issues VALUES('unexpected write')")).toThrow()
  } finally { snapshot.close(); db.close() }
})

test('incomplete ingestion, changed source manifest and unresolved issues cannot enter the baker', () => {
  for (const mode of ['incomplete', 'source', 'issue']) {
    const db = fixture(mode !== 'incomplete')
    if (mode === 'source') db.exec("UPDATE sources SET manifest='{}'")
    if (mode === 'issue') db.exec("INSERT INTO issues VALUES('conflict')")
    expect(() => canonicalRegions(db, plan, inventory)).toThrow()
    db.exec('BEGIN; ROLLBACK')
    db.close()
  }
})

test('inventory identity and full component counts are enforced', () => {
  const db = fixture()
  expect(() => canonicalRegions(db, plan, { ...inventory, planSHA256: 'f'.repeat(64) })).toThrow('inventory')
  const snapshot = canonicalRegions(db, plan, { ...inventory, regions: [{ ...inventory.regions[0]!, components: 1 }] })
  try { expect(() => [...snapshot.rows(inventory.regions[0]!.region14)]).toThrow('component') }
  finally { snapshot.close(); db.close() }
})


test('completed frozen snapshot equals canonical rows; incomplete and changed files fail', () => {
  const folder = mkdtempSync(join(tmpdir(), 'ngii-snapshot-'))
  const basePath = join(folder, 'base.sqlite'), deltaPath = join(folder, 'delta.sqlite')
  const sourceDb = fixture()
  try {
    sourceDb.exec(`VACUUM INTO '${basePath.replaceAll("'", "''")}'`)
    sourceDb.exec(`VACUUM INTO '${deltaPath.replaceAll("'", "''")}'`)
    sourceDb.close()
    const pin = (path: string) => { const s = statSync(path, { bigint: true }); return { path: path.replaceAll('\\','/'), bytes: Number(s.size), mtimeNs: s.mtimeNs.toString() } }
    const base = new Database(basePath); base.exec('CREATE TABLE observations(row_number INTEGER)'); base.close()
    const basePin = { ...pin(basePath), sourceCursors: [] }
    const delta = new Database(deltaPath)
    delta.exec('DELETE FROM buildings; CREATE TABLE observations(row_number INTEGER)')
    delta.query('INSERT INTO metadata VALUES(?,?)').run('baseIdentity', JSON.stringify(basePin)); delta.close()
    const doc = { schema: 'ngii-canonical-snapshot-v1', planSHA256: hash, complete: true, base: basePin, delta: pin(deltaPath) }
    const path = join(folder, 'snapshot.json'); writeFileSync(path, JSON.stringify(doc))
    const db = openCanonicalSnapshot(path), reader = canonicalRegions(db, plan, inventory)
    try { expect([...reader.rows(inventory.regions[0]!.region14)]).toEqual([{ ...row, provenance: { ...manifest, row: 0 } }]) }
    finally { reader.close(); db.exec('PRAGMA query_only=OFF'); expect(() => db.exec("INSERT INTO base.issues VALUES('write')")).toThrow(); db.close() }
    writeFileSync(path, JSON.stringify({ ...doc, complete: false }))
    expect(() => openCanonicalSnapshot(path)).toThrow('incomplete')
    writeFileSync(path, JSON.stringify({ ...doc, base: { ...basePin, bytes: basePin.bytes + 1 } }))
    expect(() => openCanonicalSnapshot(path)).toThrow('changed')
  } finally { rmSync(folder, { recursive: true, force: true }) }
})
