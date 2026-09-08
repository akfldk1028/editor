import { beforeEach, describe, expect, test } from 'bun:test'
import { Client } from '@modelcontextprotocol/sdk/client/index.js'
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js'
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { SceneBridge } from '../../bridge/scene-bridge'
import { registerApplyFloorPlan } from './apply-floor-plan'

type TextContent = Array<{ type: string; text: string }>

const SQUARE: Array<[number, number]> = [
  [0, 0],
  [4, 0],
  [4, 3],
  [0, 3],
]

describe('apply_floor_plan', () => {
  let client: Client
  let bridge: SceneBridge

  const call = async (args: Record<string, unknown>) => {
    const result = await client.callTool({ name: 'apply_floor_plan', arguments: args })
    return {
      isError: result.isError,
      payload: result.isError ? null : JSON.parse((result.content as TextContent)[0]!.text),
      text: (result.content as TextContent)[0]!.text,
    }
  }

  const levelId = () => Object.values(bridge.getNodes()).find((n) => n.type === 'level')!.id

  beforeEach(async () => {
    bridge = new SceneBridge()
    bridge.setScene({}, [])
    bridge.loadDefault()
    const server = new McpServer({ name: 'test', version: '0.0.0' })
    registerApplyFloorPlan(server, bridge)
    const [srvT, cliT] = InMemoryTransport.createLinkedPair()
    client = new Client({ name: 'test-client', version: '0.0.0' })
    await Promise.all([server.connect(srvT), client.connect(cliT)])
  })

  test('builds a room into an existing level', async () => {
    const { isError, payload } = await call({
      plan: { levels: [{ levelId: levelId(), rooms: [{ name: 'Study', polygon: SQUARE }] }] },
    })

    expect(isError).toBeFalsy()
    expect(payload.rooms).toHaveLength(1)
    const room = payload.rooms[0]
    expect(room.name).toBe('Study')
    expect(room.zoneId).toMatch(/^zone_/)
    expect(room.slabId).toMatch(/^slab_/)
    expect(room.ceilingId).toMatch(/^ceiling_/)
    expect(room.wallIds).toHaveLength(4)
    expect(room.areaSqMeters).toBe(12)
    expect(payload.totals).toMatchObject({ rooms: 1, walls: 4, doors: 0, windows: 0 })

    for (const wallId of room.wallIds) {
      expect(bridge.getNode(wallId)).not.toBeNull()
    }
  })

  test('cuts doors and windows into the wall the plan names', async () => {
    const { payload } = await call({
      plan: {
        levels: [
          {
            levelId: levelId(),
            rooms: [
              {
                name: 'Bedroom',
                polygon: SQUARE,
                openings: [
                  { kind: 'door', wall: 0, t: 0.5, width: 0.9 },
                  { kind: 'window', wall: 2, t: 0.5, width: 1.2, sillHeight: 0.9 },
                ],
              },
            ],
          },
        ],
      },
    })

    const room = payload.rooms[0]
    expect(room.doorIds).toHaveLength(1)
    expect(room.windowIds).toHaveLength(1)
    expect(payload.totals).toMatchObject({ doors: 1, windows: 1 })

    const door = bridge.getNode(room.doorIds[0]) as { type: string; parentId?: string } | null
    expect(door?.type).toBe('door')
    const window = bridge.getNode(room.windowIds[0]) as { type: string } | null
    expect(window?.type).toBe('window')
  })

  test('creates a level when the plan does not name one', async () => {
    const before = Object.values(bridge.getNodes()).filter((n) => n.type === 'level').length
    const { payload } = await call({
      plan: { levels: [{ label: 'Upper', rooms: [{ name: 'Loft', polygon: SQUARE }] }] },
    })

    const after = Object.values(bridge.getNodes()).filter((n) => n.type === 'level').length
    expect(after).toBe(before + 1)
    expect(payload.levelIds).toHaveLength(1)
    expect(payload.rooms[0].levelId).toBe(payload.levelIds[0])
  })

  test('dryRun reports the same shape without mutating the scene', async () => {
    const before = Object.keys(bridge.getNodes()).length
    const { payload } = await call({
      dryRun: true,
      plan: {
        levels: [
          {
            levelId: levelId(),
            rooms: [{ name: 'Kitchen', polygon: SQUARE, openings: [{ kind: 'door', wall: 0 }] }],
          },
        ],
      },
    })

    expect(payload.dryRun).toBe(true)
    expect(payload.totals).toMatchObject({ rooms: 1, walls: 4, doors: 1 })
    expect(payload.rooms[0].zoneId).toBeNull()
    expect(Object.keys(bridge.getNodes())).toHaveLength(before)
  })

  test('warns and skips an opening that names a wall the room does not have', async () => {
    const { payload } = await call({
      plan: {
        levels: [
          {
            levelId: levelId(),
            rooms: [{ name: 'Hall', polygon: SQUARE, openings: [{ kind: 'door', wall: 9 }] }],
          },
        ],
      },
    })

    expect(payload.rooms[0].doorIds).toHaveLength(0)
    expect(payload.warnings.join(' ')).toContain('wall 9')
    // The room itself is still built.
    expect(payload.rooms[0].wallIds).toHaveLength(4)
  })

  test('warns and skips an opening wider than its wall', async () => {
    const { payload } = await call({
      plan: {
        levels: [
          {
            levelId: levelId(),
            rooms: [
              {
                name: 'Nook',
                // 1m x 3m: edge 0 is only 1m long.
                polygon: [
                  [0, 0],
                  [1, 0],
                  [1, 3],
                  [0, 3],
                ],
                openings: [{ kind: 'door', wall: 0, width: 2 }],
              },
            ],
          },
        ],
      },
    })

    expect(payload.rooms[0].doorIds).toHaveLength(0)
    expect(payload.warnings.join(' ')).toMatch(/too short|wider/i)
  })

  test('rejects a level id that is not a level', async () => {
    const site = Object.values(bridge.getNodes()).find((n) => n.type === 'site')!
    const { isError, text } = await call({
      plan: { levels: [{ levelId: site.id, rooms: [{ name: 'X', polygon: SQUARE }] }] },
    })

    expect(isError).toBe(true)
    expect(text).toContain('expected level')
  })

  test('builds every room across multiple levels in one call', async () => {
    const { payload } = await call({
      plan: {
        name: 'Two storey',
        levels: [
          {
            levelId: levelId(),
            rooms: [
              { name: 'Living', polygon: SQUARE },
              {
                name: 'Kitchen',
                polygon: [
                  [4, 0],
                  [7, 0],
                  [7, 3],
                  [4, 3],
                ],
              },
            ],
          },
          { label: 'First floor', rooms: [{ name: 'Bedroom', polygon: SQUARE }] },
        ],
      },
    })

    expect(payload.rooms).toHaveLength(3)
    expect(payload.totals).toMatchObject({ levels: 2, rooms: 3, walls: 12 })
    expect(new Set(payload.rooms.map((r: { levelId: string }) => r.levelId)).size).toBe(2)
  })

  test('furnishes a room when the plan asks for it', async () => {
    const { payload } = await call({
      plan: {
        levels: [
          {
            levelId: levelId(),
            rooms: [{ name: 'Bedroom', type: 'bedroom', polygon: SQUARE, furnish: true }],
          },
        ],
      },
    })

    expect(payload.rooms[0].itemIds.length).toBeGreaterThan(0)
    expect(payload.totals.items).toBe(payload.rooms[0].itemIds.length)
  })

  test('warns when furnish is asked for without a room type', async () => {
    const { payload } = await call({
      plan: {
        levels: [{ levelId: levelId(), rooms: [{ name: 'Void', polygon: SQUARE, furnish: true }] }],
      },
    })

    expect(payload.rooms[0].itemIds).toHaveLength(0)
    expect(payload.warnings.join(' ')).toMatch(/type/i)
  })
  test('omitWalls leaves a shared boundary to the neighbouring room', async () => {
    const { payload } = await call({
      plan: {
        levels: [
          {
            levelId: levelId(),
            rooms: [
              { name: 'Left', polygon: SQUARE },
              {
                name: 'Right',
                // Shares the x=4 edge with Left, so that edge is left to Left.
                polygon: [
                  [4, 0],
                  [8, 0],
                  [8, 3],
                  [4, 3],
                ],
                omitWalls: [3],
              },
            ],
          },
        ],
      },
    })

    const [left, right] = payload.rooms
    expect(left.wallIds).toHaveLength(4)
    expect(right.wallIds).toHaveLength(3)
    expect(right.omittedWalls).toEqual([3])
    expect(payload.totals).toMatchObject({ walls: 7, omittedWalls: 1 })
  })

  test('an opening on an omitted wall is skipped with a warning, not silently dropped', async () => {
    const { payload } = await call({
      plan: {
        levels: [
          {
            levelId: levelId(),
            rooms: [
              {
                name: 'Room',
                polygon: SQUARE,
                omitWalls: [0],
                openings: [{ kind: 'door', wall: 0 }],
              },
            ],
          },
        ],
      },
    })

    expect(payload.rooms[0].doorIds).toHaveLength(0)
    expect(payload.warnings.join(' ')).toContain('omitted')
  })

  test('omitting an edge does not shift the index other openings use', async () => {
    const { payload } = await call({
      plan: {
        levels: [
          {
            levelId: levelId(),
            rooms: [
              {
                name: 'Room',
                polygon: SQUARE,
                omitWalls: [0],
                // Wall 2 must still mean polygon edge 2, not "the second wall built".
                openings: [{ kind: 'door', wall: 2, t: 0.5 }],
              },
            ],
          },
        ],
      },
    })

    const room = payload.rooms[0]
    expect(room.wallIds).toHaveLength(3)
    expect(room.doorIds).toHaveLength(1)
    const door = bridge.getNode(room.doorIds[0]) as { wallId: string }
    const wall = bridge.getNode(door.wallId) as { metadata: { edgeIndex: number } }
    expect(wall.metadata.edgeIndex).toBe(2)
  })
})
