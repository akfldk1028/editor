import { useQuery, useMutation } from '@tanstack/react-query'
import { landAPI } from '@/features/land/api'
import type { LandAnalyzeRequest } from '@/features/land/api'

export function useLandAnalyze() {
  return useMutation({
    mutationFn: (req: LandAnalyzeRequest) => landAPI.analyze(req),
  })
}

export function useLandZones() {
  return useQuery({
    queryKey: ['land', 'zones'],
    queryFn: () => landAPI.zones(),
    staleTime: 5 * 60_000,
  })
}

export function useLandStats() {
  return useQuery({
    queryKey: ['land', 'stats'],
    queryFn: () => landAPI.stats(),
    staleTime: 30_000,
  })
}
