import { createOAuthOnlyEnvironment } from "../cli/oauthEnvironment.js";
import { parseJsonRecord } from "../cli/jsonRecord.js";
import { defaultProcessRunner } from "../cli/processRunner.js";
import { buildProviderPrompt, describeCliFailure } from "../cli/providerPrompt.js";
import type {
  ChatProvider,
  ProcessRunner,
  ProviderChatRequest,
  ProviderChatResult,
  ProviderStatus
} from "../contracts.js";

export class ClaudeCliProvider implements ChatProvider {
  readonly id = "claude" as const;

  constructor(
    private readonly runner: ProcessRunner = defaultProcessRunner,
    private readonly cwd = process.cwd(),
    private readonly command = "claude"
  ) {}

  async getStatus(): Promise<ProviderStatus> {
    let result;
    try {
      result = await this.runner.run({
        command: this.command,
        args: ["auth", "status", "--json"],
        cwd: this.cwd,
        env: createOAuthOnlyEnvironment(),
        timeoutMs: 15_000
      });
    } catch {
      result = { exitCode: null, stdout: "", stderr: "", errorCode: "ENOENT" };
    }
    const status = parseJsonRecord(result.stdout);
    const authenticated =
      result.exitCode === 0 &&
      status?.loggedIn === true &&
      status?.authMethod === "claude.ai";
    const subscription =
      typeof status?.subscriptionType === "string"
        ? status.subscriptionType
        : undefined;

    return {
      id: this.id,
      label: "Claude",
      installed: result.errorCode !== "ENOENT",
      authenticated,
      authMethod: authenticated ? "claude.ai" : "unknown",
      subscription: authenticated ? subscription : undefined,
      detail: authenticated
        ? `기존 Claude 로그인 세션${subscription ? ` · ${subscription}` : ""}`
        : "Claude login unavailable; run claude auth login"
    };
  }

  async chat(request: ProviderChatRequest): Promise<ProviderChatResult> {
    const resumeArgs = request.sessionId
      ? ["--resume", request.sessionId]
      : [];
    const result = await this.runner.run({
      command: this.command,
      args: [
        "--print",
        "--output-format",
        "json",
        "--permission-mode",
        "plan",
        "--tools",
        "",
        ...resumeArgs
      ],
      cwd: this.cwd,
      env: createOAuthOnlyEnvironment(),
      stdin: buildProviderPrompt(request),
      timeoutMs: 180_000,
      signal: request.signal
    });
    if (result.exitCode !== 0) {
      throw new Error(`Claude provider failed: ${describeCliFailure(result.errorCode)}`);
    }

    const output = parseJsonRecord(result.stdout);
    if (!output) {
      throw new Error("Claude provider returned invalid JSON");
    }
    if (output.subtype !== "success" || typeof output.result !== "string") {
      throw new Error("Claude provider returned no assistant text");
    }
    return {
      provider: this.id,
      text: output.result.trim(),
      sessionId: typeof output.session_id === "string" ? output.session_id : null
    };
  }
}
