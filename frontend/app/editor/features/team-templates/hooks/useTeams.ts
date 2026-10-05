import type { TeamResponse } from '@/features/team-templates/api'
import { teamAPI, validationAPI } from '@/features/team-templates/api'
import type { Component, ComponentConfig } from '@/lib/contracts/workspace'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

export function useTeams() {
  return useQuery({
    queryKey: ['teams'],
    queryFn: teamAPI.list,
  })
}

export function useTeam(id: number | null) {
  return useQuery({
    queryKey: ['teams', id],
    queryFn: () => teamAPI.get(id!),
    enabled: id !== null,
  })
}

export function useCreateTeam() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (team: Record<string, unknown>) => teamAPI.create(team),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['teams'] })
    },
  })
}

export function useUpdateTeam() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, component, version }: { id: number; component: unknown; version: number }) =>
      teamAPI.update(id, component, version),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['teams'] }),
  })
}

export function useDeleteTeam() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => teamAPI.delete(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['teams'] }),
  })
}

export function useValidateComponent(component: Component<ComponentConfig> | null | undefined) {
  return useQuery({
    queryKey: ['validation', component ? JSON.stringify(component) : null],
    queryFn: () => validationAPI.validate(component!),
    enabled: !!component,
    retry: false,
    staleTime: 60_000,
  })
}

export function getTeamName(team: TeamResponse) {
  return team.component?.label ?? `Team #${team.id}`
}

export function getTeamPattern(team: TeamResponse) {
  const comp = team.component as Record<string, unknown> | null
  const teamType = String(comp?.team_type ?? comp?.provider ?? '')
  if (teamType.includes('RoundRobin')) return 'sequential'
  if (teamType.includes('Selector')) return 'selector'
  if (teamType.includes('Swarm')) return 'handoff'
  if (teamType.includes('MagenticOne')) return 'custom'
  // Fallback: check label for pattern hints
  const label = (team.component?.label ?? '').toLowerCase()
  if (label.includes('debate')) return 'selector'
  if (label.includes('reflection')) return 'sequential'
  if (label.includes('handoff')) return 'handoff'
  return 'custom'
}
