# Renderers

*Node renderer pattern in `frontend/components/viewer`.*

Applies to: `frontend/components/viewer/**`.

Renderers live in `frontend/components/viewer/src/components/renderers/`. Each renderer is responsible for one node type's Three.js geometry and materials — nothing else.

> **For registry-driven kinds, the default is no custom renderer.** Set `def.geometry` instead and the framework mounts a generic renderer + geometry system for you. See [node-definitions.md](node-definitions.md). The pattern below applies to kinds that *do* need a custom renderer (GLB, `<Html>`, drei, instancing, shader materials).

## Dispatch Chain

```
<SceneRenderer>          — iterates rootNodeIds from useScene
  └─ <NodeRenderer>      — switches on node.type, renders the matching component
       └─ <WallRenderer> — (or SlabRenderer, DoorRenderer, …)
```

See `frontend/components/viewer/src/components/renderers/scene-renderer.tsx` and `frontend/components/viewer/src/components/renderers/node-renderer.tsx`.

## Renderer Responsibilities

A renderer **should**:
- Read its node from `useScene` via the node's ID
- Register its mesh(es) with `useRegistry()` so other systems can look them up
- Subscribe to pointer events via `useNodeEvents()`
- Render geometry and apply materials based on node properties

A renderer **must not**:
- Run geometry generation logic (that belongs in a System)
- Import anything from `frontend/app/editor`
- Manage selection state directly (use `useViewer` for read, emit events for write)
- Perform expensive per-frame calculations in the component body

## Example — Minimal Renderer

```tsx
// frontend/components/viewer/src/components/renderers/my-node/index.tsx
import { useRegistry } from '@pascal-app/core'
import { useNodeEvents } from '../../hooks/use-node-events'
import { useScene } from '@pascal-app/core'

export function MyNodeRenderer({ node }: { node: MyNode }) {
  const ref = useRef<Mesh>(null!)
  useRegistry(node.id, 'my-node', ref)   // 3 args: id, type, ref — no return value
  const events = useNodeEvents(node, 'my-node')

  return (
    <mesh ref={ref} {...events}>
      <boxGeometry args={[node.width, node.height, node.depth]} />
      <meshStandardMaterial color={node.color} />
    </mesh>
  )
}
```

## Adding a New Node Type

For new kinds, prefer the registry-driven model in [node-definitions.md](node-definitions.md). The legacy steps below apply only when a kind needs a custom React renderer (GLB loaders, `<Html>` portals, etc.) **and** lives in `frontend/components/viewer` rather than `frontend/elements/nodes/<kind>`:

1. Create `frontend/components/viewer/src/components/renderers/<type>/index.tsx`
2. Add a case to `NodeRenderer` in `node-renderer.tsx`
3. Add the corresponding system in `resources/lib/core/src/systems/` if the node needs derived geometry
4. Export from `frontend/components/viewer/src/index.ts` if needed externally

## Performance Notes

- Use `useMemo` for geometry that depends on node properties — avoid recreating on every render.
- For complex cutout or boolean geometry, delegate to a System (e.g. `WallCutout`).
- Register one mesh per node ID; if a renderer spawns multiple meshes, use a group ref or pick the primary one for registry.
