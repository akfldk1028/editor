export type EnvironmentVariableType = 'string' | 'number' | 'boolean' | 'secret'
export interface EnvironmentVariable {
  name: string
  value: string
  type: EnvironmentVariableType
  description?: string
  required: boolean
}
export interface Settings {
  id: 1
  version: number
  config: {
    ui: {
      show_llm_call_events: boolean
      expanded_messages_by_default: boolean
      show_agent_flow_by_default: boolean
      human_input_timeout_minutes: number
    }
    environment: EnvironmentVariable[]
  }
}
