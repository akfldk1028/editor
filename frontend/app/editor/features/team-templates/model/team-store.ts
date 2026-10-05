import type { TeamResponse } from '@/features/team-templates/api'
import { create } from 'zustand'

interface TeamState {
  selectedTeamId: number | null
  selectTeam: (id: number | null) => void
  editingTeam: TeamResponse | null
  setEditingTeam: (team: TeamResponse | null) => void
}

export const useTeamStore = create<TeamState>((set) => ({
  selectedTeamId: null,
  selectTeam: (id) => set({ selectedTeamId: id }),
  editingTeam: null,
  setEditingTeam: (team) => set({ editingTeam: team }),
}))
