export interface AgentSummary {
  agent_id: string;
  label: string;
  capabilities: string[];
  implementation_status: string;
  connection_status: string;
  checked_at: string | null;
  evidence_ref: string | null;
}
