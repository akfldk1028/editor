const base = `${process.env.NEXT_PUBLIC_BASE_PATH || ''}/api/v1/workspace`
export async function workspaceRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${base}/${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json' },
    cache: 'no-store',
  })
  const body = await response.json()
  if (!response.ok)
    throw new Error(
      typeof body.detail === 'string'
        ? body.detail
        : `Workspace request failed (${response.status})`,
    )
  return body as T
}
