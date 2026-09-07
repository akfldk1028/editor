import { z } from 'zod'
import { liveSyncOutput } from '../live-sync'
import { measurement } from '../measurement'
import { ROOM_TYPES } from '../room-tools'
import { NodeIdSchema, Vec2Schema } from '../schemas'

/**
 * Room categories the furnishing pass has a layout for. Re-exported from
 * `room-tools` so the two tools can never drift apart. A plan may name a room
 * anything; only these types can be furnished automatically.
 */
export { ROOM_TYPES as FURNISHABLE_ROOM_TYPES } from '../room-tools'

const OpeningSchema = z.object({
  kind: z.enum(['door', 'window']),
  /**
   * Which of the room's walls the opening goes in, as an index into the room's
   * polygon edges: edge `i` runs from `polygon[i]` to `polygon[i + 1]`, and the
   * last edge closes back to `polygon[0]`.
   */
  wall: z.number().int().min(0),
  /** Position along the wall: 0 = start, 0.5 = centre, 1 = end. Defaults to centre. */
  t: z.number().min(0).max(1).optional(),
  width: measurement('length', 'm', { positive: true, description: 'Opening width.' }).optional(),
  height: measurement('length', 'm', { positive: true, description: 'Opening height.' }).optional(),
  /** Windows only. Ignored for doors. */
  sillHeight: measurement('length', 'm', {
    min: 0,
    description: 'Window sill height above the floor.',
  }).optional(),
  /** Doors only. Ignored for windows. */
  hingesSide: z.enum(['left', 'right']).optional(),
  /** Doors only. Ignored for windows. */
  swingDirection: z.enum(['inward', 'outward']).optional(),
})

const RoomSchema = z.object({
  name: z.string().min(1),
  /** Drives the furnishing pass. Omit for a room that should stay empty. */
  type: z.enum(ROOM_TYPES).optional(),
  /**
   * Room outline in metres on the XZ plane, in order. Three points minimum.
   * Do not repeat the first point at the end — the outline closes itself.
   */
  polygon: z.array(Vec2Schema).min(3),
  color: z.string().optional(),
  wallHeight: measurement('length', 'm', {
    positive: true,
    description: 'Wall height.',
  }).optional(),
  wallThickness: measurement('length', 'm', {
    positive: true,
    description: 'Wall thickness.',
  }).optional(),
  openings: z.array(OpeningSchema).default([]),
  /** Place furniture for `type`. Requires `type`; ignored without one. */
  furnish: z.boolean().default(false),
})

const LevelSchema = z.object({
  /**
   * Write into an existing level instead of creating one. When omitted a new
   * level is appended above the building's current top level.
   */
  levelId: NodeIdSchema.optional(),
  label: z.string().optional(),
  height: measurement('length', 'm', {
    min: 0,
    description: 'Floor-to-floor storey height.',
  }).optional(),
  rooms: z.array(RoomSchema).min(1),
})

export const FloorPlanSchema = z.object({
  name: z.string().optional(),
  levels: z.array(LevelSchema).min(1),
})

export type FloorPlan = z.infer<typeof FloorPlanSchema>
export type FloorPlanRoom = z.infer<typeof RoomSchema>
export type FloorPlanOpening = z.infer<typeof OpeningSchema>

export const applyFloorPlanInput = {
  plan: FloorPlanSchema,
  /**
   * Report what would be created without touching the scene. Geometry and
   * opening fits are still checked, so this is the cheap way for a planning
   * agent to validate a draft before committing it.
   */
  dryRun: z.boolean().default(false),
}

const RoomResultSchema = z.object({
  name: z.string(),
  levelId: z.string(),
  zoneId: z.string().nullable(),
  slabId: z.string().nullable(),
  ceilingId: z.string().nullable(),
  wallIds: z.array(z.string()),
  doorIds: z.array(z.string()),
  windowIds: z.array(z.string()),
  itemIds: z.array(z.string()),
  areaSqMeters: z.number(),
})

export const applyFloorPlanOutput = {
  dryRun: z.boolean(),
  levelIds: z.array(z.string()),
  rooms: z.array(RoomResultSchema),
  totals: z.object({
    levels: z.number(),
    rooms: z.number(),
    walls: z.number(),
    doors: z.number(),
    windows: z.number(),
    items: z.number(),
    areaSqMeters: z.number(),
  }),
  /** Non-fatal problems: a skipped opening, a room type that cannot be furnished. */
  warnings: z.array(z.string()),
  ...liveSyncOutput,
}
