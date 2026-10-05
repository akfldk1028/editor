import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { sessionsApi } from '../api'

export function useSessions() {
  return useQuery({ queryKey: ['workspace', 'sessions'], queryFn: sessionsApi.list })
}

export function useSessionRuns(id: number | null) {
  return useQuery({
    queryKey: ['workspace', 'sessions', id, 'runs'],
    queryFn: () => sessionsApi.runs(id!),
    enabled: id !== null,
  })
}

export function useDeleteSession() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: sessionsApi.archive,
    onSuccess: () => client.invalidateQueries({ queryKey: ['workspace', 'sessions'] }),
  })
}
