import { readFileSync, statSync, existsSync } from 'node:fs'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { Database } from 'bun:sqlite'
import { inflateSync } from 'node:zlib'
import { tileXY } from '../features/world/lib/building-geometry'
import type { CanonicalBuilding } from './ngii-mesh-input'

export type CanonicalPlan = { schema: string; storageSchema: string; planSHA256: string; expectedRows: number;
  sources: { id: string; expectedRows: number; manifest: CanonicalBuilding['provenance'] }[] }
export type CanonicalRegionInventory = { schema: string; planSHA256: string; sourceComplete: boolean;
  sourceRows: number; buildingCount: number; regionCount: number;
  regions: { region14: string; buildings: number; components: number }[] }

/** One read transaction feeds every region; no nationwide NDJSON copy is needed. */
export function canonicalRegions(db: Database, plan: CanonicalPlan, inventory: CanonicalRegionInventory) {
  if (plan.schema !== 'ngii-canonical-plan-v1' || plan.storageSchema !== 'canonical-sqlite-v2'
    || !/^[a-f0-9]{64}$/.test(plan.planSHA256) || !plan.sources.length
    || plan.sources.reduce((n, s) => n + s.expectedRows, 0) !== plan.expectedRows) throw Error('Invalid canonical source plan')
  if (inventory.schema !== 'ngii-canonical-regions-v1' || inventory.planSHA256 !== plan.planSHA256
    || !inventory.sourceComplete || inventory.sourceRows !== plan.expectedRows
    || inventory.regionCount !== inventory.regions.length
    || inventory.regions.reduce((n, r) => n + r.buildings, 0) !== inventory.buildingCount) throw Error('Invalid canonical region inventory')
  const regions = new Map(inventory.regions.map(r => [r.region14, r]))
  if (regions.size !== inventory.regionCount || inventory.regions.some(r => !/^14\/\d+\/\d+$/.test(r.region14)
    || !Number.isInteger(r.buildings) || r.buildings < 1 || !Number.isInteger(r.components) || r.components < r.buildings)) throw Error('Invalid canonical region inventory counts')
  db.exec('PRAGMA query_only=ON; BEGIN')
  try {
    const identity = db.query<{ value: string }, [string]>('SELECT value FROM metadata WHERE key=?').get('planSHA256')
    if (identity?.value !== plan.planSHA256) throw Error('Canonical database plan mismatch')
    const sources = db.query<{ id: string; expected_rows: number; next_row: number; status: string; manifest: string }, []>('SELECT id,expected_rows,next_row,status,manifest FROM sources').all()
    if (sources.length !== plan.sources.length) throw Error('Canonical source list mismatch')
    const manifests = new Map<string, CanonicalBuilding['provenance']>()
    for (const row of sources) {
      const expected = plan.sources.find(s => s.id === row.id)
      if (!expected || row.expected_rows !== expected.expectedRows || row.next_row !== row.expected_rows || row.status !== 'complete') throw Error('Canonical source ingest incomplete')
      const manifest = JSON.parse(row.manifest)
      if (JSON.stringify(manifest) !== JSON.stringify(expected.manifest) || manifest.productCode !== 'B021'
        || manifest.family !== 'NGII-B021' || manifest.productKind !== 'continuous-topographic') throw Error('Canonical source manifest mismatch')
      manifests.set(row.id, manifest)
    }
    if (db.query<{ count: number }, []>('SELECT count(*) AS count FROM issues').get()!.count) throw Error('Unresolved canonical source issues')
    if (db.query<{ count: number }, []>('SELECT count(*) AS count FROM buildings').get()!.count !== inventory.buildingCount) throw Error('Canonical building count differs from inventory')
    const query = db.query<{ id: string; payload: Uint8Array }, [string]>('SELECT id,payload FROM buildings WHERE region14=? ORDER BY region16,id')
    return {
      regions: inventory.regions,
      *rows(region: string): Generator<CanonicalBuilding> {
        const expected = regions.get(region)
        if (!expected) throw Error('Region absent from canonical inventory')
        let buildings = 0, components = 0
        for (const stored of query.iterate(region)) {
          const row = JSON.parse(inflateSync(stored.payload).toString('utf8'))
          const ref = row.provenance, manifest = manifests.get(ref.sourceId)
          if (!manifest || !Number.isInteger(ref.row) || ref.row < 0 || row.canonicalBuildingId !== stored.id) throw Error('Invalid canonical row provenance')
          const [x, y] = tileXY(row.anchorWGS84[0], row.anchorWGS84[1], 14)
          if (`14/${x}/${y}` !== region) throw Error('Canonical owner region mismatch')
          row.provenance = { ...manifest, row: ref.row }
          buildings++
          components += row.geomWGS84.type === 'Polygon' ? 1 : row.geomWGS84.type === 'MultiPolygon' ? row.geomWGS84.coordinates.length : 0
          yield row
        }
        if (buildings !== expected.buildings || components !== expected.components) throw Error('Canonical region building/component count mismatch')
      },
      close: () => { db.exec('ROLLBACK') },
    }
  } catch (error) {
    db.exec('ROLLBACK')
    throw error
  }
}

/** Frozen compressed base and completed delta expose the unchanged canonical SQL schema. */
export function openCanonicalSnapshot(path: string): Database {
  const snapshot = JSON.parse(readFileSync(path, 'utf8'))
  if (snapshot.schema !== 'ngii-canonical-snapshot-v1' || snapshot.complete !== true
    || !/^[a-f0-9]{64}$/.test(snapshot.planSHA256)) throw Error('Canonical snapshot incomplete or invalid')
  for (const name of ['base', 'delta']) {
    const pin = snapshot[name]
    const stamp = statSync(pin.path, { bigint: true })
    if (resolve(pin.path).replaceAll('\\', '/') !== pin.path || stamp.size !== BigInt(pin.bytes)
      || stamp.mtimeNs.toString() !== pin.mtimeNs
      || (existsSync(pin.path + '-wal') && statSync(pin.path + '-wal').size !== 0)) throw Error('Canonical snapshot file changed')
  }
  const db = new Database(':memory:', 0x02 | 0x04 | 0x40) // READWRITE | CREATE | URI; attached files use mode=ro
  try {
    for (const name of ['base', 'delta']) {
      const uri = pathToFileURL(snapshot[name].path); uri.searchParams.set('mode', 'ro')
      db.query(`ATTACH DATABASE ? AS ${name}`).run(uri.href)
    }
    db.exec(`CREATE TEMP VIEW metadata AS SELECT * FROM delta.metadata;
      CREATE TEMP VIEW sources AS SELECT * FROM delta.sources;
      CREATE TEMP VIEW buildings AS SELECT * FROM base.buildings UNION ALL SELECT * FROM delta.buildings;
      CREATE TEMP VIEW observations AS SELECT * FROM base.observations UNION ALL SELECT * FROM delta.observations;
      CREATE TEMP VIEW issues AS SELECT * FROM base.issues UNION ALL SELECT * FROM delta.issues;`)
    const binding = db.query<{value: string}, [string]>('SELECT value FROM metadata WHERE key=?').get('baseIdentity')
    const stable = (value: unknown): string => JSON.stringify(value, (_key, item) => item && typeof item === 'object' && !Array.isArray(item) ? Object.fromEntries(Object.entries(item).sort(([a], [b]) => a.localeCompare(b))) : item)
    if (!binding || stable(JSON.parse(binding.value)) !== stable(snapshot.base)
      || db.query<{value: string}, [string]>('SELECT value FROM metadata WHERE key=?').get('planSHA256')?.value !== snapshot.planSHA256)
      throw Error('Canonical snapshot binding mismatch')
    db.exec('PRAGMA query_only=ON')
    return db
  } catch (error) { db.close(); throw error }
}
