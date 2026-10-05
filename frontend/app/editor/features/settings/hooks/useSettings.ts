import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { settingsAPI } from '../api/settings'
import type { Settings } from '../model/types'

export function useSettings() {
  return useQuery({
    queryKey: ['settings'],
    queryFn: () => settingsAPI.get(),
    retry: false,
  })
}

export function useUpdateSettings() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (settings: Settings) => settingsAPI.update(settings),
    onSuccess: (saved) => {
      queryClient.setQueryData(['settings'], saved)
    },
  })
}
