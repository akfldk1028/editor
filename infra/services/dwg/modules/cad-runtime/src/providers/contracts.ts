import type {
  ProviderChatResult,
  ProviderId,
  ProviderStatus
} from "@dwg/contracts";

export type {
  ProviderChatResult,
  ProviderId,
  ProviderStatus
} from "@dwg/contracts";

export interface ProviderChatRequest {
  message: string;
  systemPrompt: string;
  context: string;
  sessionId?: string | null;
  signal?: AbortSignal;
}

export interface ChatProvider {
  readonly id: ProviderId;
  getStatus(): Promise<ProviderStatus>;
  chat(request: ProviderChatRequest): Promise<ProviderChatResult>;
}

export interface ProcessRunSpec {
  command: string;
  args: string[];
  cwd: string;
  env: NodeJS.ProcessEnv;
  stdin?: string;
  timeoutMs?: number;
  signal?: AbortSignal;
}

export interface ProcessResult {
  exitCode: number | null;
  stdout: string;
  stderr: string;
  errorCode?: string;
}

export interface ProcessRunner {
  run(spec: ProcessRunSpec): Promise<ProcessResult>;
}
