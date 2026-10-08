/** The browser Vworld key, or null when the backend has none configured. */
export async function browserKey(): Promise<string | null> {
  try {
    const response = await fetch(`${process.env.NEXT_PUBLIC_BASE_PATH || ''}/api/v1/land/map-config`)
    if (!response.ok) return null
    const body = (await response.json()) as { api_key?: string }
    return body.api_key || null
  } catch {
    return null
  }
}
