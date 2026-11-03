/** Begin the read now, but leave restoration and error handling to the mounted engine. */
export function prefetchSavedSite<T>(load: (signal: AbortSignal) => Promise<T>) {
  const controller = new AbortController()
  const result = load(controller.signal).then(
    value => ({ ok: true as const, value }),
    error => ({ ok: false as const, error }),
  )
  return {
    abort: () => controller.abort(),
    async read(): Promise<T> {
      const settled = await result
      if (!settled.ok) throw settled.error
      return settled.value
    },
  }
}
