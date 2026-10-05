import { describe, expect, test } from 'bun:test'
import { BoxGeometry, Group, Mesh, MeshBasicMaterial, Vector3 } from 'three'
import { renderedSceneBounds } from './rendered-scene-bounds'

describe('rendered scene framing', () => {
  test('includes offset vertices and all ancestor transforms without changing the scene', () => {
    const root = new Group()
    root.position.set(100, 3, -10)
    const mesh = new Mesh(new BoxGeometry(20, 17, 10), new MeshBasicMaterial())
    mesh.geometry.translate(44, 8.5, -34)
    root.add(mesh)
    const bounds = renderedSceneBounds([root])!
    expect(bounds.getCenter(new Vector3()).toArray()).toEqual([144, 11.5, -44])
    expect(bounds.getSize(new Vector3()).toArray()).toEqual([20, 17, 10])
    expect(root.position.toArray()).toEqual([100, 3, -10])
    expect(mesh.position.toArray()).toEqual([0, 0, 0])
  })

  test('waits for actual rendered geometry and ignores hidden objects and editor overlays', () => {
    const root = new Group()
    expect(renderedSceneBounds([root])).toBeNull()
    const hidden = new Mesh(new BoxGeometry(1000, 1000, 1000))
    hidden.visible = false
    const overlay = new Mesh(new BoxGeometry(1000, 1000, 1000))
    overlay.layers.set(1)
    const mesh = new Mesh(new BoxGeometry(2, 4, 6))
    root.add(hidden, overlay, mesh)
    expect(renderedSceneBounds([root])!.getSize(new Vector3()).toArray()).toEqual([2, 4, 6])
    root.visible = false
    expect(renderedSceneBounds([root])).toBeNull()
  })
})
