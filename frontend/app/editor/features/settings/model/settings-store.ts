import { create } from 'zustand'

interface SettingsStoreState {
  showLlmEvents: boolean
  expandMessages: boolean
  showAgentFlow: boolean
  humanInputTimeout: number
  setShowLlmEvents: (v: boolean) => void
  setExpandMessages: (v: boolean) => void
  setShowAgentFlow: (v: boolean) => void
  setHumanInputTimeout: (v: number) => void
  hydrate: (ui: {
    show_llm_call_events: boolean
    expanded_messages_by_default?: boolean
    show_agent_flow_by_default?: boolean
    human_input_timeout_minutes?: number
  }) => void
}

export const useSettingsStore = create<SettingsStoreState>((set) => ({
  showLlmEvents: false,
  expandMessages: false,
  showAgentFlow: false,
  humanInputTimeout: 3,
  setShowLlmEvents: (v) => set({ showLlmEvents: v }),
  setExpandMessages: (v) => set({ expandMessages: v }),
  setShowAgentFlow: (v) => set({ showAgentFlow: v }),
  setHumanInputTimeout: (v) => set({ humanInputTimeout: Math.max(1, Math.min(30, v)) }),
  hydrate: (ui) =>
    set({
      showLlmEvents: ui.show_llm_call_events,
      expandMessages: ui.expanded_messages_by_default ?? false,
      showAgentFlow: ui.show_agent_flow_by_default ?? false,
      humanInputTimeout: ui.human_input_timeout_minutes ?? 3,
    }),
}))
