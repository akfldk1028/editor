import { useQuery } from '@tanstack/react-query'
import { workspaceRequest } from '@/lib/workspace-request'
export function useHealth() {
  return useQuery({
    queryKey: ['workspace-health'],
    queryFn: () => workspaceRequest<{ status: boolean }>('health'),
    refetchInterval: 30000,
  })
}
export function useVersion() {
  return useQuery({
    queryKey: ['workspace-version'],
    queryFn: () => workspaceRequest<{ version: string }>('version'),
  })
}
