#!/usr/bin/env bun
/**
 * Send a floor plan to Pascal and open it in the editor.
 *
 *   bun run resources/scripts/plan-to-3d.ts <plan.json> [--dry-run] [--name "My plan"]
 *   cat plan.json | bun run resources/scripts/plan-to-3d.ts - --name "My plan"
 *
 * The plan file is the `plan` argument of the `apply_floor_plan` MCP tool —
 * see docs/mcp/floor-plan.md for the format. This drives the real MCP server
 * over stdio, which is exactly what a planning agent does; use it to try a plan
 * by hand, or as a reference for wiring an agent up.
 *
 * Scenes are written to the SQLite store the editor reads, so the result is
 * reachable at http://localhost:3002/scene/<id> once `bun dev` is running.
 */
import path from 'node:path'
import { parseArgs } from 'node:util'
import { Client } from '@modelcontextprotocol/sdk/client/index.js'
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js'

const repositoryRoot = path.resolve(import.meta.dirname, '../..')

const { values, positionals } = parseArgs({
  allowPositionals: true,
  options: {
    'dry-run': { type: 'boolean', default: false },
    name: { type: 'string' },
    'editor-url': { type: 'string', default: 'http://localhost:3002' },
    help: { type: 'boolean', default: false },
  },
})

if (values.help || positionals.length !== 1) {
  console.log(
    'Usage: bun run resources/scripts/plan-to-3d.ts <plan.json|-> [--dry-run] [--name <name>]',
  )
  process.exit(values.help ? 0 : 1)
}

const source = positionals[0]!
const raw = source === '-' ? await Bun.stdin.text() : await Bun.file(path.resolve(source)).text()

let plan: unknown
try {
  plan = JSON.parse(raw)
} catch (error) {
  console.error(`Could not parse ${source} as JSON: ${(error as Error).message}`)
  process.exit(1)
}

// Accept either a bare plan or the full tool payload `{ "plan": ... }`.
if (typeof plan === 'object' && plan !== null && 'plan' in plan) {
  plan = (plan as { plan: unknown }).plan
}

const text = (result: unknown) =>
  (result as { content: Array<{ text: string }> }).content[0]?.text ?? ''

/** Tool errors come back as plain prose, not JSON — report them as errors. */
const json = (result: unknown) => {
  const body = text(result)
  if ((result as { isError?: boolean }).isError) {
    throw new Error(body || 'the tool reported an error with no message')
  }
  try {
    return JSON.parse(body)
  } catch {
    throw new Error(`unexpected response: ${body.slice(0, 400)}`)
  }
}

const client = new Client({ name: 'plan-to-3d', version: '1.0.0' })
await client.connect(
  new StdioClientTransport({
    command: process.execPath,
    args: ['run', `${repositoryRoot}/backend/mcp/src/bin/pascal-mcp.ts`, '--stdio'],
    cwd: repositoryRoot,
  }),
)

try {
  if (values['dry-run']) {
    const result = json(
      await client.callTool({ name: 'apply_floor_plan', arguments: { plan, dryRun: true } }),
    )
    report(result)
    process.exit(result.warnings.length > 0 ? 1 : 0)
  }

  // Bind a scene first so the build persists and reaches the open editor.
  const sceneName =
    values.name ??
    (typeof plan === 'object' && plan !== null && 'name' in plan
      ? String((plan as { name: unknown }).name)
      : 'Floor plan')
  const scene = json(await client.callTool({ name: 'save_scene', arguments: { name: sceneName } }))

  const levelId = text(await client.callTool({ name: 'get_scene', arguments: {} })).match(
    /"(level_[A-Za-z0-9_-]+)"/,
  )?.[1]

  // A first level that names no id builds on the scene's existing ground level
  // rather than stacking an empty one under it.
  const levels = (plan as { levels?: Array<{ levelId?: string }> }).levels
  if (levelId && Array.isArray(levels) && levels[0] && !levels[0].levelId) {
    levels[0].levelId = levelId
  }

  const result = json(await client.callTool({ name: 'apply_floor_plan', arguments: { plan } }))
  report(result)

  const verify = json(await client.callTool({ name: 'verify_scene', arguments: {} }))
  console.log(`verify_scene: ${verify.ok ? 'ok' : 'PROBLEMS'}`)
  if (!verify.ok && Array.isArray(verify.issues)) {
    for (const issue of verify.issues) console.log(`  - ${JSON.stringify(issue)}`)
  }

  console.log(`\nOpen: ${values['editor-url']}/scene/${scene.id}`)
} finally {
  await client.close()
}

function report(result: {
  dryRun: boolean
  totals: Record<string, number>
  rooms: Array<{ name: string; areaSqMeters: number }>
  warnings: string[]
}): void {
  const t = result.totals
  console.log(
    `${result.dryRun ? '[dry run] ' : ''}${t.rooms} rooms across ${t.levels} level(s): ` +
      `${t.walls} walls, ${t.doors} doors, ${t.windows} windows, ${t.items} items, ${t.areaSqMeters} m²`,
  )
  for (const room of result.rooms) {
    console.log(`  ${room.name.padEnd(16)} ${room.areaSqMeters} m²`)
  }
  if (result.warnings.length > 0) {
    console.log(`\n${result.warnings.length} warning(s):`)
    for (const warning of result.warnings) console.log(`  - ${warning}`)
  }
}
