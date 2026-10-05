import { Box3, Layers, type Mesh, type Object3D } from 'three'

export function renderedSceneBounds(roots: Iterable<Object3D>, layers = new Layers()): Box3 | null {
  const bounds = new Box3()
  const part = new Box3()
  const visited = new Set<Object3D>()
  for (const root of roots) {
    root.updateWorldMatrix(true, true)
    root.traverseVisible(object => {
      if (visited.has(object)) return
      visited.add(object)
      const mesh = object as Mesh
      if (!mesh.isMesh || !mesh.geometry || !mesh.layers.test(layers)) return
      mesh.geometry.computeBoundingBox()
      if (!mesh.geometry.boundingBox) return
      part.copy(mesh.geometry.boundingBox).applyMatrix4(mesh.matrixWorld)
      if (!part.isEmpty() && [...part.min.toArray(), ...part.max.toArray()].every(Number.isFinite)) bounds.union(part)
    })
  }
  return bounds.isEmpty() ? null : bounds
}
