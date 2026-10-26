/** Loading GeoJSON is asynchronous; a cleared/replaced parcel must stay cleared. */
export async function addCurrentSetback<T extends { name?: string }>(source: Promise<T>,
  viewer: { isDestroyed(): boolean; dataSources: { add(source: T): unknown; remove(source: T, destroy: boolean): unknown } },
  current: () => boolean, name: string): Promise<void> {
  const value = await source
  if (!current() || viewer.isDestroyed()) return
  value.name = name
  await viewer.dataSources.add(value)
  // Cesium adds even an already loaded source on a microtask, after clear may run.
  if (!viewer.isDestroyed() && !current()) viewer.dataSources.remove(value, true)
}
