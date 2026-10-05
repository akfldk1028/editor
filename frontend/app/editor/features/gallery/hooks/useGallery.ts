import { teamAPI } from '@/features/team-templates/api'
import type { Component, TeamConfig } from '@/lib/contracts/workspace'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { galleryAPI } from '../api'

export function useGalleries() {
  return useQuery({
    queryKey: ['galleries'],
    queryFn: galleryAPI.list,
  })
}

export function useImportGalleryTeam() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (team: Component<TeamConfig>) => teamAPI.create({ component: team }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['teams'] })
    },
  })
}

export function useSyncGallery() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (url: string) => galleryAPI.sync(url),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['galleries'] })
    },
  })
}
