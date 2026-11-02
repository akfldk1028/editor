export class GroundSourceUnavailable extends Error {}

export async function groundSource(url: string, get: typeof fetch = fetch,
  delay: (ms: number) => Promise<void> = ms => new Promise(resolve => setTimeout(resolve, ms))) {
  let reason = ''
  for (let attempt = 0; attempt < 6; attempt++) {
    let response: Response | undefined
    try { response = await get(url, { signal: AbortSignal.timeout(90000) }) }
    catch (error) { reason = String(error) }
    if (response?.ok) return response
    if (response && response.status !== 429 && response.status < 500) throw new Error(`HTTP ${response.status}`)
    if (response) reason = `HTTP ${response.status}`
    if (attempt < 5) await delay(Math.min(30000, 1000 * 2 ** attempt))
  }
  throw new GroundSourceUnavailable(`Source unavailable after retries: ${reason}`)
}
