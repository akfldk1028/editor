import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import type { AnyNode, AnyNodeId } from '@pascal-app/core/schema'
import {
  CeilingNode,
  DoorNode,
  LevelNode,
  SlabNode,
  WallNode,
  WindowNode,
  ZoneNode,
} from '@pascal-app/core/schema'
import type { SceneOperations } from '../../operations'
import { ErrorCode, throwMcpError } from '../errors'
import { polygonArea, type Vec2, wallLength, wallLocalXFromT } from '../geometry'
import { persistencePayload, publishLiveSceneSnapshot } from '../live-sync'
import { planRoomFurniture } from '../room-tools'
import { applyFloorPlanInput, applyFloorPlanOutput, type FloorPlanRoom } from './schema'

const DEFAULT_LEVEL_HEIGHT = 2.5
const DEFAULT_DOOR = { width: 0.9, height: 2.1 }
const DEFAULT_WINDOW = { width: 1.2, height: 1.2, sillHeight: 0.9 }

type RoomResult = {
  name: string
  levelId: string
  zoneId: string | null
  slabId: string | null
  ceilingId: string | null
  wallIds: string[]
  doorIds: string[]
  windowIds: string[]
  itemIds: string[]
  areaSqMeters: number
}

function assertLevel(bridge: SceneOperations, levelId: string): AnyNode {
  const node = bridge.getNode(levelId as AnyNodeId)
  if (!node) {
    throwMcpError(ErrorCode.InvalidParams, `Level not found: ${levelId}`)
  }
  if (node.type !== 'level') {
    throwMcpError(ErrorCode.InvalidParams, `Node ${levelId} is a ${node.type}, expected level`)
  }
  return node
}

/** The building every new level is appended to. */
function resolveBuildingId(bridge: SceneOperations): AnyNodeId {
  const building = Object.values(bridge.getNodes()).find((node) => node.type === 'building')
  if (!building) {
    throwMcpError(
      ErrorCode.InvalidParams,
      'The scene has no building to append a level to. Name an existing levelId, or load a scene that has one.',
    )
  }
  return building.id as AnyNodeId
}

function appendLevel(
  bridge: SceneOperations,
  buildingId: AnyNodeId,
  label: string | undefined,
  height: number | undefined,
): AnyNodeId {
  const ordinals = bridge
    .getChildren(buildingId)
    .filter((node) => node.type === 'level')
    .map((node) => node.level)
  const node = LevelNode.parse({
    level: Math.max(-1, ...ordinals) + 1,
    height: height ?? DEFAULT_LEVEL_HEIGHT,
    children: [],
    ...(label !== undefined ? { name: label, metadata: { label } } : {}),
  })
  return bridge.createNode(node, buildingId) as AnyNodeId
}

/** Zone, slab, ceiling and one wall per polygon edge — the same shape `create_room` builds. */
function buildRoomShell(room: FloorPlanRoom) {
  const points = room.polygon as Vec2[]
  const metadata = { mcpTool: 'apply_floor_plan', roomName: room.name }
  const zone = ZoneNode.parse({
    name: room.name,
    polygon: points,
    color: room.color ?? '#60a5fa',
    metadata,
  })
  const slab = SlabNode.parse({ polygon: points, metadata })
  const ceiling = CeilingNode.parse({ polygon: points, metadata })
  const walls = points.map((start, index) =>
    WallNode.parse({
      name: `${room.name} wall ${index + 1}`,
      start,
      end: points[(index + 1) % points.length],
      ...(room.wallHeight !== undefined ? { height: room.wallHeight } : {}),
      ...(room.wallThickness !== undefined ? { thickness: room.wallThickness } : {}),
      metadata: { ...metadata, edgeIndex: index },
    }),
  )
  return { zone, slab, ceiling, walls, points }
}

/**
 * Build the opening nodes a room asks for, skipping any that cannot fit and
 * explaining why. `walls` is indexed by polygon edge, matching `opening.wall`.
 */
function buildOpenings(
  room: FloorPlanRoom,
  walls: Array<ReturnType<typeof WallNode.parse>>,
): { doors: AnyNode[]; windows: AnyNode[]; warnings: string[] } {
  const doors: AnyNode[] = []
  const windows: AnyNode[] = []
  const warnings: string[] = []

  for (const opening of room.openings) {
    const wall = walls[opening.wall]
    if (!wall) {
      warnings.push(
        `${room.name}: ${opening.kind} skipped — wall ${opening.wall} does not exist (the room has ${walls.length} walls, 0-${walls.length - 1}).`,
      )
      continue
    }

    const isDoor = opening.kind === 'door'
    const defaults = isDoor ? DEFAULT_DOOR : DEFAULT_WINDOW
    const width = opening.width ?? defaults.width
    const height = opening.height ?? defaults.height
    const length = wallLength(wall)

    if (length < width) {
      warnings.push(
        `${room.name}: ${opening.kind} skipped — wall ${opening.wall} is ${length.toFixed(2)}m long, too short for a ${width.toFixed(2)}m ${opening.kind}.`,
      )
      continue
    }

    const t = opening.t ?? 0.5
    const localX = wallLocalXFromT(wall, t, width)

    if (isDoor) {
      doors.push(
        DoorNode.parse({
          wallId: wall.id,
          parentId: wall.id,
          position: [localX, height / 2, 0],
          width,
          height,
          ...(opening.hingesSide ? { hingesSide: opening.hingesSide } : {}),
          ...(opening.swingDirection ? { swingDirection: opening.swingDirection } : {}),
        }),
      )
    } else {
      const sillHeight = opening.sillHeight ?? DEFAULT_WINDOW.sillHeight
      windows.push(
        WindowNode.parse({
          wallId: wall.id,
          parentId: wall.id,
          position: [localX, sillHeight + height / 2, 0],
          width,
          height,
        }),
      )
    }
  }

  return { doors, windows, warnings }
}

/** Index of the first wall carrying a door — furniture is laid out facing away from it. */
function doorWallIndex(room: FloorPlanRoom): number {
  const door = room.openings.find((opening) => opening.kind === 'door')
  return door ? door.wall : 0
}

export function registerApplyFloorPlan(server: McpServer, bridge: SceneOperations): void {
  server.registerTool(
    'apply_floor_plan',
    {
      title: 'Apply floor plan',
      description:
        'Build a whole floor plan in one call: levels, rooms (zone, slab, ceiling, walls), doors, windows and optional furniture. Openings name a wall by its polygon edge index. Use dryRun to validate a plan without changing the scene. This is the tool a planning agent should call instead of orchestrating create_room/add_door/add_window itself.',
      inputSchema: applyFloorPlanInput,
      outputSchema: applyFloorPlanOutput,
    },
    async ({ plan, dryRun }) => {
      const warnings: string[] = []
      const rooms: RoomResult[] = []
      const levelIds: string[] = []

      // Validate every named level up front so a bad id fails before any writes.
      for (const level of plan.levels) {
        if (level.levelId) assertLevel(bridge, level.levelId)
      }

      for (const level of plan.levels) {
        let levelId: string
        if (level.levelId) {
          levelId = level.levelId
        } else if (dryRun) {
          // Nothing is created in a dry run, so there is no id to report yet.
          levelId = `<new level ${levelIds.length + 1}>`
        } else {
          levelId = appendLevel(
            bridge,
            resolveBuildingId(bridge),
            level.label,
            level.height,
          ) as string
        }
        levelIds.push(levelId)

        for (const room of level.rooms) {
          const { zone, slab, ceiling, walls, points } = buildRoomShell(room)
          const openings = buildOpenings(room, walls)
          warnings.push(...openings.warnings)

          if (dryRun) {
            rooms.push({
              name: room.name,
              levelId,
              zoneId: null,
              slabId: null,
              ceilingId: null,
              wallIds: walls.map((wall) => wall.id as string),
              doorIds: openings.doors.map((door) => door.id as string),
              windowIds: openings.windows.map((window) => window.id as string),
              itemIds: [],
              areaSqMeters: Math.round(polygonArea(points) * 100) / 100,
            })
            continue
          }

          bridge.applyPatch([
            { op: 'create', node: zone, parentId: levelId as AnyNodeId },
            { op: 'create', node: slab, parentId: levelId as AnyNodeId },
            { op: 'create', node: ceiling, parentId: levelId as AnyNodeId },
            ...walls.map((wall) => ({
              op: 'create' as const,
              node: wall,
              parentId: levelId as AnyNodeId,
            })),
            ...openings.doors.map((door) => ({
              op: 'create' as const,
              node: door,
              parentId: door.parentId as AnyNodeId,
            })),
            ...openings.windows.map((window) => ({
              op: 'create' as const,
              node: window,
              parentId: window.parentId as AnyNodeId,
            })),
          ])

          // Furniture is planned against the committed scene so it can avoid the
          // doors and walls this room just added, and earlier rooms' items.
          let itemIds: string[] = []
          if (room.furnish) {
            if (room.type) {
              const furniture = planRoomFurniture(bridge, {
                levelId,
                polygon: points,
                roomType: room.type,
                doorWallIndex: doorWallIndex(room),
                mcpTool: 'apply_floor_plan',
              })
              if (furniture.items.length > 0) {
                bridge.applyPatch(
                  furniture.items.map((item) => ({
                    op: 'create' as const,
                    node: item,
                    parentId: levelId as AnyNodeId,
                  })),
                )
              }
              itemIds = furniture.items.map((item) => item.id as string)
              warnings.push(
                ...furniture.skipped.map((reason) => `${room.name}: furniture skipped — ${reason}`),
              )
            } else {
              warnings.push(
                `${room.name}: furnish was requested but the room has no type, so there is no furniture layout to apply.`,
              )
            }
          }

          rooms.push({
            name: room.name,
            levelId,
            zoneId: zone.id as string,
            slabId: slab.id as string,
            ceilingId: ceiling.id as string,
            wallIds: walls.map((wall) => wall.id as string),
            doorIds: openings.doors.map((door) => door.id as string),
            windowIds: openings.windows.map((window) => window.id as string),
            itemIds,
            areaSqMeters: Math.round(polygonArea(points) * 100) / 100,
          })
        }
      }

      const totals = {
        levels: plan.levels.length,
        rooms: rooms.length,
        walls: rooms.reduce((sum, room) => sum + room.wallIds.length, 0),
        doors: rooms.reduce((sum, room) => sum + room.doorIds.length, 0),
        windows: rooms.reduce((sum, room) => sum + room.windowIds.length, 0),
        items: rooms.reduce((sum, room) => sum + room.itemIds.length, 0),
        areaSqMeters:
          Math.round(rooms.reduce((sum, room) => sum + room.areaSqMeters, 0) * 100) / 100,
      }

      const persistence = dryRun
        ? undefined
        : await publishLiveSceneSnapshot(bridge, 'apply_floor_plan')

      const payload = {
        dryRun,
        levelIds,
        rooms,
        totals,
        warnings,
        ...(persistence ? persistencePayload(persistence) : {}),
      }
      return {
        content: [{ type: 'text' as const, text: JSON.stringify(payload) }],
        structuredContent: payload,
      }
    },
  )
}
